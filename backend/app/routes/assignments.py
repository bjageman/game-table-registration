"""Assignments API routes."""

import logging
import secrets
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.announcements import (
    deliver_event,
    enqueue,
    enqueue_instructions,
)
from app.announcements import (
    status as announcement_status,
)
from app.assignment_finalization import approve
from app.assignment_preferences import for_event as preferences_for_event
from app.context import ApplicationContext
from app.message_cleanup import remove_signup_message
from app.models import (
    Announcement,
    Event,
    LotteryRun,
)
from app.schemas import (
    RetryAnnouncementInput,
)
from app.withdrawals import current_result


def register(context: ApplicationContext) -> None:
    router = APIRouter()
    authenticated = context.authenticated
    destination = context.destination
    engine = context.engine
    list_names = context.list_names
    scoped_discord = context.scoped_discord

    @router.post("/api/events/{event_id}/assignments/approve")
    def approve_assignments(
        event_id: str, request: Request, delete_signup_message: bool = False
    ) -> dict[str, Any]:
        authenticated(request, True)
        with DBSession(engine) as db:
            event = context.scoped_event(db, event_id, request)
            if delete_signup_message:
                remove_signup_message(context, db, event, request)
                db.commit()
        approve(engine, event_id, destination(request).discord_channel_id)
        try:
            deliver_event(engine, scoped_discord(request), event_id)
        except Exception:
            # The durable queue continues delivery after a transient failure.
            logging.getLogger(__name__).exception(
                "Approved assignments remain queued for %s", event_id
            )
        with DBSession(engine) as db:
            return context.serialize(context.scoped_event(db, event_id, request))

    @router.get("/api/events/{event_id}/announcement")
    def announcement(event_id: str, request: Request) -> dict[str, Any]:
        authenticated(request)
        with DBSession(engine) as db:
            event = context.scoped_event(db, event_id, request)
            guild_id = event.guild_id
        return announcement_status(engine, event_id, guild_id)

    @router.post("/api/events/{event_id}/announcement/retry")
    def retry_announcement(
        event_id: str, body: RetryAnnouncementInput, request: Request
    ) -> dict[str, Any]:
        authenticated(request, True)
        with DBSession(engine) as db:
            event = context.scoped_event(db, event_id, request)
            run = db.get(LotteryRun, event_id)
            if event.status != "assigned" or run is None:
                raise HTTPException(409, "Placements have not been determined yet")
            if event.archived_at is not None:
                raise HTTPException(409, "Archived events cannot be announced again")
            existing = db.scalar(
                select(Announcement.id)
                .where(
                    Announcement.event_id == event_id, Announcement.kind == "assignment"
                )
                .limit(1)
            )
            creating = existing is None
            announcement_channel = (
                event.channel_id or destination(request).discord_channel_id
            )
            if creating:
                enqueue(
                    db,
                    event,
                    announcement_channel,
                    current_result(db, run),
                    run.snapshot,
                )
            else:
                enqueue_instructions(db, event, announcement_channel)
            rows = list(
                db.scalars(
                    select(Announcement).where(
                        Announcement.event_id == event_id,
                        Announcement.kind.in_(["assignment", "instructions"]),
                        Announcement.state != "sent",
                    )
                )
            )
            if any(row.state == "sending" or row.token for row in rows):
                raise HTTPException(409, "Announcement delivery is already in progress")
            if (
                any(row.unknown or row.state == "needs_review" for row in rows)
                and not body.confirm_repost
            ):
                raise HTTPException(
                    409, "Check Discord before confirming a possible repost"
                )
            for row in rows:
                changed = db.execute(
                    update(Announcement)
                    .where(
                        Announcement.id == row.id,
                        Announcement.state.in_(["pending", "needs_review"]),
                        Announcement.token.is_(None),
                        Announcement.attempts == row.attempts,
                    )
                    .values(
                        state="pending",
                        next_attempt=time.time(),
                        unknown=False,
                        lease_until=None,
                        error=None,
                    )
                    .returning(Announcement.id)
                ).scalar_one_or_none()
                if not changed:
                    db.rollback()
                    raise HTTPException(
                        409, "Delivery changed while retrying. Refresh its status."
                    )
            guild_id = event.guild_id
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                if not creating or not db.scalar(
                    select(Announcement.id)
                    .where(Announcement.event_id == event_id)
                    .limit(1)
                ):
                    raise
        deliver_event(engine, scoped_discord(request), event_id)
        return announcement_status(engine, event_id, guild_id)

    @router.post("/api/events/{event_id}/share")
    def share_event(event_id: str, request: Request) -> dict[str, str]:
        authenticated(request, True)
        with DBSession(engine) as db:
            event = context.scoped_event(db, event_id, request)
            if event.status != "assigned":
                raise HTTPException(409, "Only assigned events can be shared")
            token = secrets.token_urlsafe(32)
            db.execute(
                update(Event)
                .where(Event.id == event_id, Event.public_share_token.is_(None))
                .values(public_share_token=token)
            )
            db.commit()
            db.refresh(event)
            return {"path": f"/#/shared/{event.public_share_token}"}

    @router.get("/api/public/events/{token}")
    def public_event(token: str, response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        with DBSession(engine) as db:
            event = db.scalar(select(Event).where(Event.public_share_token == token))
            if event is None or event.status != "assigned":
                raise HTTPException(404, "Shared event not found")
            run = db.get(LotteryRun, event.id)
            if run is None:
                raise HTTPException(404, "Shared event not found")
            rows = list_names(
                current_result(db, run)["tables"], event.id, include_settings=False
            )
            preferences = preferences_for_event(db, event)
            return {
                "title": event.title,
                "timezone": preferences.timezone if preferences else None,
                "description": event.description,
                "location": event.location,
                "starts_at": event.starts_at,
                "archived": event.archived_at is not None,
                "tables": [
                    {
                        "name": row["name"],
                        "capacity": next(
                            t["capacity"]
                            for t in event.tables
                            if t["name"] == row["name"]
                        ),
                        **{
                            key: [
                                {"name": player.get("display_name") or player["name"]}
                                for player in row.get(key, [])
                            ]
                            for key in ("players", "waitlist")
                        },
                    }
                    for row in rows
                ],
            }

    @router.get("/api/events/{event_id}/assignments")
    def assignments(event_id: str, request: Request) -> dict[str, Any]:
        authenticated(request)
        with DBSession(engine) as db:
            context.scoped_event(db, event_id, request)
            run = db.get(LotteryRun, event_id)
            if run is None:
                raise HTTPException(409, "Placements have not been determined yet")
            return {
                "version": run.version,
                "seed": run.seed,
                "snapshot": run.snapshot,
                "result": run.result,
                "current_result": current_result(db, run),
                "created_at": run.created_at,
            }

    context.app.include_router(router)
