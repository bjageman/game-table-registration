"""Player profiles and reciprocal pairing within the selected organization."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.context import ApplicationContext
from app.models import Event, LotteryRun, PlayerProfile, TableSignup
from app.schemas import PlayerPairInput, PlayerProfileInput


def register(context: ApplicationContext) -> None:
    router = APIRouter()
    engine = context.engine

    def profile_data(
        db: DBSession,
        request: Request,
        player_id: str,
        profile: PlayerProfile | None,
        name: str | None = None,
    ) -> dict[str, Any]:
        result = context.player_data(player_id, profile, name)
        partner = (
            context.player_scope(request).get(db, profile.partner_id)
            if profile and profile.partner_id
            else None
        )
        result["partner"] = (
            {
                "id": partner.discord_id,
                "name": partner.real_name or partner.discord_name,
            }
            if partner
            else None
        )
        return result

    def known_players(db: DBSession, request: Request) -> dict[str, dict[str, Any]]:
        scope = context.player_scope(request)
        event_filters = (
            Event.guild_id == scope.guild_id,
            Event.organization_id == request.state.organization_id
            if request.state.organization_id
            else Event.organization_id.is_(None)
            & (Event.created_by == request.state.user_id),
        )
        found = {
            p.discord_id: context.player_data(p.discord_id, p)
            for p in db.scalars(select(PlayerProfile).where(*scope.filters()))
        }
        for player_id, name in db.execute(
            select(TableSignup.discord_id, TableSignup.discord_name)
            .join(Event, Event.id == TableSignup.event_id)
            .where(*event_filters)
        ):
            found.setdefault(player_id, context.player_data(player_id, None, name))
        for snapshot in db.scalars(
            select(LotteryRun.snapshot)
            .join(Event, Event.id == LotteryRun.event_id)
            .where(*event_filters)
        ):
            for player in snapshot.get("players", []):
                player_id = str(player.get("id", ""))
                name = player.get("name")
                if player_id and isinstance(name, str):
                    found.setdefault(
                        player_id, context.player_data(player_id, None, name)
                    )
                    if player.get("is_test"):
                        found[player_id]["is_test"] = True
        return found

    @router.get("/api/players")
    def players(request: Request) -> list[dict[str, Any]]:
        context.authenticated(request)
        with DBSession(engine) as db:
            found = known_players(db, request)
            return sorted(
                found.values(),
                key=lambda p: (
                    (p["real_name"] or p["discord_name"]).casefold(),
                    p["discord_id"],
                ),
            )

    @router.get("/api/players/{player_id}")
    def player_profile(
        player_id: str, request: Request, signup_name: str | None = None
    ) -> dict[str, Any]:
        context.authenticated(request)
        context.valid_player_id(player_id)
        with DBSession(engine) as db:
            profile = context.player_scope(request).get(db, player_id)
            if player_id.startswith("test-") and (
                profile is None or not profile.is_test
            ):
                raise HTTPException(404, "Test player not found")
            return profile_data(db, request, player_id, profile, signup_name)

    @router.put("/api/players/{player_id}")
    def save_player_profile(
        player_id: str, body: PlayerProfileInput, request: Request
    ) -> dict[str, Any]:
        context.authenticated(request, True)
        context.valid_player_id(player_id)
        changes = body.model_dump(exclude_none=True)
        if not changes:
            raise HTTPException(422, "Specify a profile setting to update")
        scope = context.player_scope(request)
        with DBSession(engine) as db:
            profile = scope.get(db, player_id)
            if player_id.startswith("test-") and (
                profile is None or not profile.is_test
            ):
                raise HTTPException(404, "Test player not found")
            if profile is None:
                profile = scope.create(
                    player_id, discord_name=context.discord_name(player_id)
                )
                db.add(profile)
            for key, value in changes.items():
                setattr(profile, key, value)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                profile = scope.get(db, player_id)
                if profile is None:
                    raise
                for key, value in changes.items():
                    setattr(profile, key, value)
                db.commit()
            return profile_data(db, request, player_id, profile)

    @router.put("/api/players/{player_id}/partner")
    def save_partner(
        player_id: str, body: PlayerPairInput, request: Request
    ) -> dict[str, Any]:
        context.authenticated(request, True)
        context.valid_player_id(player_id)
        if body.partner_id:
            context.valid_player_id(body.partner_id)
        if body.partner_id == player_id:
            raise HTTPException(422, "A player cannot be linked to themselves")
        scope = context.player_scope(request)
        with DBSession(engine) as db:
            # Lock in a consistent order so concurrent re-pairings stay reciprocal.
            scope.lock(db)
            profiles = {
                p.discord_id: p
                for p in db.scalars(
                    select(PlayerProfile)
                    .where(*scope.filters())
                    .order_by(PlayerProfile.discord_id)
                    .with_for_update()
                )
            }
            known = known_players(db, request)
            for pid in (player_id, body.partner_id):
                if pid and pid not in known:
                    raise HTTPException(404, "Player not found in this organization")
            target = profiles.get(body.partner_id) if body.partner_id else None
            if (
                target
                and target.partner_id
                and target.partner_id != player_id
                and target.partner_id != body.replace_partner_id
            ):
                previous = profiles.get(target.partner_id)
                previous_name = (
                    (previous.real_name or previous.discord_name)
                    if previous
                    else target.partner_id
                )
                return {
                    "confirmation_required": True,
                    "replace_partner_id": target.partner_id,
                    "message": "Linking these players will break the link between "
                    f"{target.real_name or target.discord_name} and "
                    f"{previous_name}. Continue?",
                }
            for pid in (player_id, body.partner_id):
                if pid and pid not in profiles:
                    data = known[pid]
                    profiles[pid] = scope.create(
                        pid, discord_name=data["discord_name"], is_test=data["is_test"]
                    )
                    db.add(profiles[pid])
            source = profiles[player_id]
            for profile in (source, target):
                if profile and profile.partner_id:
                    previous = profiles.get(profile.partner_id)
                    if previous and previous.partner_id == profile.discord_id:
                        previous.partner_id = None
                    profile.partner_id = None
            source.partner_id = body.partner_id
            if body.partner_id:
                profiles[body.partner_id].partner_id = player_id
            try:
                db.commit()
            except IntegrityError:
                raise HTTPException(
                    409, "Player links changed. Refresh and try again."
                ) from None
            return {"profile": profile_data(db, request, player_id, source)}

    context.app.include_router(router)
