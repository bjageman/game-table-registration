"""Signups API routes."""

import logging
from functools import partial
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session as DBSession

from app.announcements import (
    deliver_event,
)
from app.closing import close_and_assign
from app.context import ApplicationContext
from app.event_threads import queue_member
from app.message_cleanup import remove_signup_message as remove_signup_message_service
from app.models import (
    Event,
    EventManagerSignup,
    EventPlayerSetting,
    LotteryRun,
    PlayerProfile,
    TableSignup,
)
from app.player_profiles import for_event as player_scope_for_event
from app.publication import mark_signup_closed
from app.schemas import (
    AssignedAddInput,
    EventPlayerSettingInput,
    ManagerSignupInput,
    TestPopulationInput,
)
from app.signup_exports import event_csv, event_pdf, summary_csv
from app.signups import apply_manager_signups, table_rows
from app.test_signups import (
    add_to_rows,
)
from app.test_signups import (
    allowed as test_users_allowed,
)
from app.test_signups import (
    generate as generate_test_users,
)
from app.waitlists import add_player as add_waitlist_player
from app.withdrawals import current_result, manager_add, manager_remove


def register(context: ApplicationContext) -> None:
    router = APIRouter()
    authenticated = context.authenticated
    config = context.config
    destination = context.destination
    engine = context.engine
    event_scope = context.event_scope
    list_names = context.list_names
    matches_destination = context.matches_destination
    scoped_discord = context.scoped_discord
    serialize = context.serialize
    valid_player_id = context.valid_player_id
    remove_signup_message = partial(remove_signup_message_service, context)

    @router.get("/api/events/{event_id}/signups")
    def event_signups(event_id: str, request: Request) -> list[dict[str, Any]]:
        authenticated(request)
        custom_result: list[dict[str, Any]] | None = None
        with DBSession(engine) as db:
            event = context.scoped_event(db, event_id, request)
            if event.status in ("assigned", "review"):
                run = db.get(LotteryRun, event_id)
                if run is None:
                    raise HTTPException(503, "Saved placements are unavailable")
                rows: list[dict[str, Any]] = current_result(db, run)["tables"]
                return list_names(rows, event_id)
            message_id = event.message_id
            tables = event.tables
            population = event.test_signups
            if event.signup_mode in ("custom", "reactions"):
                custom_result = apply_manager_signups(
                    db, event, add_to_rows(table_rows(db, event), population)
                )
                db.rollback()
        if custom_result is not None:
            return list_names(custom_result, event_id)
        rows = (
            scoped_discord(request).table_signups(message_id, tables)
            if message_id
            else [{"name": table["name"], "players": []} for table in tables]
        )
        with DBSession(engine) as db:
            event = context.scoped_event(db, event_id, request)
            rows = apply_manager_signups(db, event, add_to_rows(rows, population))
            db.rollback()
        return list_names(rows, event_id)

    @router.get("/api/events/{event_id}/signups.csv")
    def download_event_csv(event_id: str, request: Request) -> Response:
        with DBSession(engine) as db:
            event = db.get(Event, event_id)
            authenticated(request)
            if event is None or not matches_destination(event, request):
                raise HTTPException(404, "Event not found")
            if event.status not in ("assigned", "review"):
                raise HTTPException(409, "Signups must be assigned before export")
        rows = event_signups(event_id, request)
        return Response(
            event_csv(rows),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="signups-{event_id}.csv"',
                "Cache-Control": "no-store",
            },
        )

    @router.get("/api/events/{event_id}/signups.pdf")
    def download_event_pdf(
        event_id: str, request: Request, timezone: str = "UTC"
    ) -> Response:
        authenticated(request)
        try:
            time_zone = ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise HTTPException(400, "Invalid timezone") from None
        with DBSession(engine) as db:
            event = context.scoped_event(db, event_id, request)
            if event.status != "assigned":
                raise HTTPException(409, "Signups must be assigned before export")
            rows = event_signups(event_id, request)
            content = event_pdf(event, rows, time_zone)
        return Response(
            content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="signups-{event_id}.pdf"',
                "Cache-Control": "no-store",
            },
        )

    @router.get("/api/exports/signups.csv")
    def download_summary_csv(request: Request) -> Response:
        authenticated(request)
        with DBSession(engine) as db:
            selected = list(
                db.scalars(
                    select(Event)
                    .where(*event_scope(request))
                    .order_by(Event.starts_at, Event.id)
                )
            )
            data = [(event, event_signups(event.id, request)) for event in selected]
            content = summary_csv(data)
        return Response(
            content,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="all-event-signups.csv"',
                "Cache-Control": "no-store",
            },
        )

    @router.put("/api/events/{event_id}/manager-players/{player_id}")
    def add_manager_player(
        event_id: str, player_id: str, body: ManagerSignupInput, request: Request
    ) -> dict[str, Any]:
        authenticated(request, True)
        valid_player_id(player_id)
        with DBSession(engine) as db:
            assigned_event = db.get(Event, event_id)
            assigned_guild = (
                assigned_event.guild_id
                if assigned_event is not None
                and matches_destination(assigned_event, request)
                and assigned_event.status in ("assigned", "review")
                else None
            )
        if assigned_guild:
            if not manager_add(
                engine,
                assigned_guild,
                event_id,
                player_id,
                body.table,
                allow_known_player=True,
            ):
                raise HTTPException(409, "Player is already assigned or unavailable")
            return {"ok": True}
        with DBSession(engine) as db:
            claimed = db.execute(
                update(Event)
                .where(
                    Event.id == event_id,
                    *event_scope(request),
                    Event.status.in_(["draft", "scheduled", "open"]),
                )
                .values(status=Event.status)
                .returning(Event.id)
            ).scalar_one_or_none()
            if not claimed:
                raise HTTPException(409, "Only draft or open signups can be changed")
            event = context.scoped_event(db, event_id, request)
            if body.table not in {table["name"] for table in event.tables}:
                raise HTTPException(422, "Unknown table")
            profile = player_scope_for_event(event).get(db, player_id)
            if player_id.startswith("test-") and (
                profile is None or not profile.is_test
            ):
                raise HTTPException(404, "Player not found")
            override = db.get(EventManagerSignup, (event_id, player_id))
            if override is None:
                override = EventManagerSignup(
                    event_id=event_id,
                    discord_id=player_id,
                    discord_name=body.name.strip(),
                    choices=[body.table],
                    removed=False,
                )
                db.add(override)
            else:
                override.discord_name = body.name.strip()
                override.choices = sorted(set(override.choices) | {body.table})
                override.removed = False
            queue_member(db, event, player_id)
            event.signup_roster_checked_at = None
            db.commit()
            return {"ok": True}

    @router.post("/api/events/{event_id}/waitlisted-players/{player_id}")
    def add_waitlisted_player(
        event_id: str, player_id: str, body: AssignedAddInput, request: Request
    ) -> dict[str, Any]:
        authenticated(request, True)
        valid_player_id(player_id)
        with DBSession(engine) as db:
            event = context.scoped_event(db, event_id, request)
            guild_id = event.guild_id
        if not add_waitlist_player(engine, guild_id, event_id, player_id, body.table):
            raise HTTPException(409, "Player cannot be added to this waitlist")
        return {"ok": True}

    @router.post("/api/events/{event_id}/assigned-players/{player_id}")
    def add_assigned_player(
        event_id: str, player_id: str, body: AssignedAddInput, request: Request
    ) -> dict[str, Any]:
        authenticated(request, True)
        valid_player_id(player_id)
        with DBSession(engine) as db:
            event = context.scoped_event(db, event_id, request)
            guild_id = event.guild_id
        if not manager_add(engine, guild_id, event_id, player_id, body.table):
            raise HTTPException(409, "Player is not available on this table's waitlist")
        return {"ok": True}

    @router.delete("/api/events/{event_id}/manager-players/{player_id}")
    def remove_manager_player(
        event_id: str, player_id: str, request: Request
    ) -> dict[str, Any]:
        authenticated(request, True)
        valid_player_id(player_id)
        with DBSession(engine) as db:
            event = context.scoped_event(db, event_id, request)
            assigned_guild = (
                event.guild_id if event.status in ("assigned", "review") else None
            )
        if assigned_guild:
            if not manager_remove(engine, assigned_guild, event_id, player_id):
                raise HTTPException(409, "Player is not currently assigned")
            return {"ok": True}
        with DBSession(engine) as db:
            claimed = db.execute(
                update(Event)
                .where(
                    Event.id == event_id,
                    *event_scope(request),
                    Event.status.in_(["draft", "scheduled", "open"]),
                )
                .values(status=Event.status)
                .returning(Event.id)
            ).scalar_one_or_none()
            if not claimed:
                raise HTTPException(409, "Only draft or open signups can be changed")
            event = context.scoped_event(db, event_id, request)
            override = db.get(EventManagerSignup, (event_id, player_id))
            if override is None:
                override = EventManagerSignup(
                    event_id=event_id,
                    discord_id=player_id,
                    discord_name="",
                    choices=[],
                    removed=True,
                )
                db.add(override)
            else:
                override.choices = []
                override.removed = True
            if event.signup_mode in ("custom", "reactions"):
                signup = db.get(TableSignup, (event_id, player_id))
                if signup is not None:
                    db.delete(signup)
            event.signup_roster_checked_at = None
            db.commit()
            return {"ok": True}

    @router.put("/api/events/{event_id}/players/{player_id}/settings")
    def save_event_player_setting(
        event_id: str, player_id: str, body: EventPlayerSettingInput, request: Request
    ) -> dict[str, Any]:
        authenticated(request, True)
        valid_player_id(player_id)
        fields = body.model_fields_set
        if not fields or not fields <= {"weighting", "guaranteed_table"}:
            raise HTTPException(422, "Specify a weight or guaranteed table")
        with DBSession(engine) as db:
            # Serialize edits against the closing claim.
            claimed = db.execute(
                update(Event)
                .where(
                    Event.id == event_id, *event_scope(request), Event.status == "open"
                )
                .values(status=Event.status)
                .returning(Event.id)
            ).scalar_one_or_none()
            if not claimed:
                raise HTTPException(409, "Only open signups can be changed")
            event = context.scoped_event(db, event_id, request)
            if "guaranteed_table" in fields and body.guaranteed_table is not None:
                if body.guaranteed_table not in {
                    table["name"] for table in event.tables
                }:
                    raise HTTPException(422, "Unknown table")
                signed_up = any(
                    p["id"] == player_id and body.guaranteed_table in p["choices"]
                    for p in (event.test_signups or {}).get("players", [])
                )
                if event.signup_mode in ("custom", "reactions"):
                    signup = db.get(TableSignup, (event_id, player_id))
                    signed_up = signed_up or bool(
                        signup and body.guaranteed_table in signup.choices
                    )
                elif event.message_id and not signed_up:
                    signed_up = any(
                        row["name"] == body.guaranteed_table
                        and any(p["id"] == player_id for p in row["players"])
                        for row in scoped_discord(request).table_signups(
                            event.message_id, event.tables
                        )
                    )
                if not signed_up:
                    raise HTTPException(422, "Player is not signed up for that table")
            setting = db.get(EventPlayerSetting, (event_id, player_id))
            if setting is None:
                setting = EventPlayerSetting(event_id=event_id, discord_id=player_id)
                db.add(setting)
            if "weighting" in fields:
                setting.weighting = body.weighting
            if "guaranteed_table" in fields:
                setting.guaranteed_table = body.guaranteed_table
            db.commit()
            profile = player_scope_for_event(event).get(db, player_id)
            return {
                "weighting": setting.weighting
                if setting.weighting is not None
                else profile.weighting
                if profile
                else 5.0,
                "guaranteed_table": setting.guaranteed_table,
                "guaranteed_seat": profile.guaranteed_seat if profile else False,
            }

    @router.post("/api/events/{event_id}/close")
    def close_signups(
        event_id: str, request: Request, delete_signup_message: bool = False
    ) -> Response:
        session = authenticated(request, True)
        with DBSession(engine) as db:
            event = context.scoped_event(db, event_id, request)
        complete = close_and_assign(
            engine,
            scoped_discord(request),
            event_id,
            session.user_id,
            destination(request).discord_channel_id,
        )
        if complete:
            if event.message_id and not event.signup_deleted_at:
                try:
                    mark_signup_closed(
                        scoped_discord(request), event.message_id, event.signup_mode
                    )
                except Exception:
                    logging.getLogger(__name__).exception(
                        "Could not mark signup message closed; "
                        "further signups are rejected"
                    )
            try:
                deliver_event(engine, scoped_discord(request), event_id)
            except Exception:
                logging.getLogger(__name__).exception(
                    "Immediate announcement attempt failed; delivery remains queued"
                )
            if delete_signup_message:
                with DBSession(engine) as db:
                    saved = db.get(Event, event_id)
                    assert saved is not None
                    remove_signup_message(db, saved, request)
                    db.commit()
        with DBSession(engine) as db:
            event = context.scoped_event(db, event_id, request)
            return JSONResponse(serialize(event), status_code=200 if complete else 202)

    @router.post("/api/events/{event_id}/test-users")
    def populate_test_users(
        event_id: str, body: TestPopulationInput, request: Request
    ) -> dict[str, Any]:
        session = authenticated(request, True)
        if not test_users_allowed(session.user_id, config):
            raise HTTPException(
                403, "Test signup population is restricted to allowlisted operators"
            )
        with DBSession(engine) as db:
            event = context.scoped_event(db, event_id, request)
            population = (
                generate_test_users(event_id, event.tables, body.players)
                if body.players
                else None
            )
            changed = db.execute(
                update(Event)
                .where(
                    Event.id == event_id,
                    *event_scope(request),
                    Event.status.in_(["draft", "scheduled", "open"]),
                )
                .values(test_signups=population)
                .returning(Event.id)
            ).scalar_one_or_none()
            if not changed:
                raise HTTPException(
                    409, "Test users can only be changed before signups close"
                )
            saved_tests = (
                list(
                    db.scalars(
                        select(PlayerProfile)
                        .where(
                            *player_scope_for_event(event).filters(),
                            PlayerProfile.is_test.is_(True),
                        )
                        .order_by(PlayerProfile.discord_name, PlayerProfile.discord_id)
                        .limit(body.players)
                    )
                )
                if population
                else []
            )
            for index, player in enumerate(population["players"] if population else []):
                if index < len(saved_tests):
                    saved = saved_tests[index]
                    player.update(
                        id=saved.discord_id,
                        name=saved.discord_name,
                        weight=saved.weighting,
                    )
                else:
                    player["name"] = f"Test Player {index + 1:03d}"
                    player["weight"] = 5.0
                    db.add(
                        PlayerProfile(
                            scope_key=player_scope_for_event(event).key,
                            guild_id=event.guild_id,
                            discord_id=player["id"],
                            discord_name=player["name"],
                            real_name="",
                            weighting=5.0,
                            is_test=True,
                        )
                    )
            # Persist the final identities after reusing saved profiles.
            db.execute(
                update(Event)
                .where(Event.id == event_id)
                .values(test_signups=population)
            )
            db.commit()
            db.refresh(event)
            return serialize(event)

    context.app.include_router(router)
