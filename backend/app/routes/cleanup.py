"""Cleanup API routes."""

import time
from functools import partial
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session as DBSession

from app.context import ApplicationContext
from app.message_cleanup import (
    delete_discord_messages_batch as delete_discord_messages_batch_service,
)
from app.message_cleanup import remove_signup_message as remove_signup_message_service
from app.models import (
    Announcement,
    Event,
    LotteryRun,
    SignupInteraction,
    TableSignup,
)


def register(context: ApplicationContext) -> None:
    router = APIRouter()
    authenticated = context.authenticated
    engine = context.engine
    event_scope = context.event_scope
    scoped_discord = context.scoped_discord
    serialize = context.serialize
    remove_signup_message = partial(remove_signup_message_service, context)
    delete_discord_messages_batch = partial(
        delete_discord_messages_batch_service, context
    )

    @router.post("/api/events/{event_id}/signup-message/delete")
    def delete_signup_message(event_id: str, request: Request) -> dict[str, Any]:
        authenticated(request, True)
        with DBSession(engine) as db:
            event = context.scoped_event(db, event_id, request)
            if event.status != "assigned":
                raise HTTPException(409, "Close signups before deleting the message")
            remove_signup_message(db, event, request)
            db.commit()
            return serialize(event)

    @router.post("/api/events/{event_id}/discord-messages/delete")
    def delete_discord_messages(event_id: str, request: Request) -> dict[str, Any]:
        authenticated(request, True)
        return delete_discord_messages_batch(event_id, request)

    @router.post("/api/events/{event_id}/archive")
    def archive_event(
        event_id: str, request: Request, delete_discord_messages: bool = False
    ) -> dict[str, Any]:
        authenticated(request, True)
        with DBSession(engine) as db:
            event = context.scoped_event(db, event_id, request)
            if event.status != "assigned" or db.get(LotteryRun, event_id) is None:
                raise HTTPException(409, "Only assigned events can be archived")
            db.execute(
                update(Event)
                .where(
                    Event.id == event_id,
                    *event_scope(request),
                    Event.status == "assigned",
                    Event.archived_at.is_(None),
                )
                .values(archived_at=time.time())
            )
            db.commit()
        return delete_discord_messages_batch(
            event_id, request, promotions_only=not delete_discord_messages
        )

    @router.delete("/api/events/{event_id}", status_code=204)
    def delete_event(
        event_id: str, request: Request, delete_poll: bool = False
    ) -> Response:
        authenticated(request, True)
        with DBSession(engine) as db:
            # Claim deletion atomically, keeping the transaction open until the
            # optional Discord operation succeeds. Failures roll back this row.
            changed = db.execute(
                update(Event)
                .where(
                    Event.id == event_id,
                    *event_scope(request),
                    Event.status.in_(["draft", "scheduled", "open", "review"]),
                )
                .values(status=Event.status)
                .returning(Event.message_id, Event.signup_roster_messages)
            ).first()
            if changed is None:
                raise HTTPException(
                    409,
                    "Only drafts, open signups, and assignments awaiting review "
                    "can be deleted.",
                )
            if delete_poll:
                event = context.scoped_event(db, event_id, request)
                for warning in db.scalars(
                    select(Announcement).where(
                        Announcement.event_id == event_id,
                        Announcement.kind == "warning",
                    )
                ):
                    client = scoped_discord(request).at(
                        event.guild_id, warning.channel_id
                    )
                    message_id = warning.message_id
                    if not message_id and warning.unknown:
                        message_id = client.find_announcement(
                            warning.channel_id,
                            warning.payload,
                            warning.attempted_at or warning.created_at,
                        )
                    if message_id and not warning.deleted_at:
                        client.delete_poll(message_id)
                # Retain the event transaction until every tracked message is
                # deleted. A retry can safely repeat successful DELETEs (404).
                ids = [item["id"] for item in changed.signup_roster_messages or []]
                if changed.message_id:
                    ids.append(changed.message_id)
                for message_id in dict.fromkeys(ids):
                    scoped_discord(request).delete_poll(message_id)
            db.execute(delete(Announcement).where(Announcement.event_id == event_id))
            db.execute(delete(LotteryRun).where(LotteryRun.event_id == event_id))
            db.execute(delete(Event).where(Event.id == event_id))
            db.execute(delete(TableSignup).where(TableSignup.event_id == event_id))
            db.execute(
                delete(SignupInteraction).where(SignupInteraction.event_id == event_id)
            )
            db.commit()
        return Response(status_code=204)

    context.app.include_router(router)
