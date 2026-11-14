"""Message cleanup services shared by API routes and workers."""

import time
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.context import ApplicationContext
from app.discord_api import DiscordRequestError
from app.models import (
    Announcement,
    Event,
)


def remove_signup_message(
    context: ApplicationContext, db: DBSession, event: Event, request: Request
) -> None:
    config = context.config
    scoped_discord = context.scoped_discord
    if event.message_id and not event.signup_deleted_at:
        scoped_discord(request).at(
            event.guild_id, event.channel_id or config.discord_channel_id
        ).delete_poll(event.message_id)
        event.signup_deleted_at = time.time()


def delete_discord_messages_batch(
    context: ApplicationContext,
    event_id: str,
    request: Request,
    promotions_only: bool = False,
) -> dict[str, Any]:
    engine = context.engine
    scoped_discord = context.scoped_discord
    serialize = context.serialize
    with DBSession(engine) as db:
        event = context.scoped_event(db, event_id, request)
        if event.status != "assigned" or event.archived_at is None:
            raise HTTPException(409, "Archive the event before deleting its messages")
        query = select(Announcement).where(
            Announcement.event_id == event_id,
            Announcement.kind != "refresh",
        )
        if promotions_only:
            query = query.where(Announcement.kind == "promotion")
        rows = list(db.scalars(query.order_by(Announcement.part)))

        def progress(
            retry_after: float = 0, error: str | None = None
        ) -> dict[str, Any]:
            remaining = sum(not row.deleted_at for row in rows) + bool(
                event.update_thread_id
            )
            if not promotions_only:
                remaining += bool(event.message_id and not event.signup_deleted_at)
            return {
                **serialize(event),
                "discord_cleanup_remaining": remaining,
                "discord_cleanup_retry_after": retry_after,
                "discord_cleanup_error": error,
            }

        def failed(failure: DiscordRequestError) -> dict[str, Any]:
            if failure.discord_status == 429:
                return progress(
                    retry_after=failure.retry_after if failure.retry_after > 0 else 1
                )
            status = failure.discord_status or "network"
            return progress(
                error=f"Discord deletion failed ({status}). "
                "Retry the remaining messages."
            )

        now = time.time()
        for row in rows:
            if row.kind == "promotion" and (row.unknown or row.state == "needs_review"):
                discord = scoped_discord(request).at(event.guild_id, row.channel_id)
                message_id = None
                try:
                    message_id = discord.find_announcement(
                        row.channel_id,
                        row.payload,
                        row.attempted_at or row.created_at,
                    )
                    if message_id:
                        discord.delete_poll(message_id)
                except DiscordRequestError as failure:
                    if message_id:
                        row.message_id = message_id
                        row.state = "sent"
                        row.error = "Promotion notice deletion failed."
                        db.commit()
                    return failed(failure)
                except HTTPException as failure:
                    return progress(
                        error=f"Promotion notice cleanup failed: {failure.detail}"
                    )
                row.message_id = message_id
                row.state = "sent"
                row.deleted_at = now
                row.unknown = False
                row.error = None
            if (
                promotions_only
                and row.kind == "promotion"
                and row.state in ("pending", "needs_review")
                and not row.message_id
                and not row.unknown
            ):
                row.state = "sent"
                row.deleted_at = now
                row.token = None
                row.lease_until = None
        db.commit()

        if any(row.state == "needs_review" for row in rows):
            return progress(
                error="An assignment announcement needs review before its "
                "Discord messages can be deleted."
            )
        if any(
            not row.deleted_at and (row.state != "sent" or not row.message_id)
            for row in rows
        ):
            return progress(retry_after=2)
        targets = [row for row in rows if not row.deleted_at]
        for row in targets if promotions_only else targets[:3]:
            assert row.message_id is not None
            try:
                scoped_discord(request).at(event.guild_id, row.channel_id).delete_poll(
                    row.message_id
                )
            except DiscordRequestError as failure:
                return failed(failure)
            row.deleted_at = time.time()
            db.commit()
        if (
            not promotions_only
            and len(targets) < 3
            and event.message_id
            and not event.signup_deleted_at
        ):
            try:
                remove_signup_message(context, db, event, request)
            except DiscordRequestError as failure:
                return failed(failure)
            db.commit()
        if event.update_thread_id:
            try:
                scoped_discord(request).delete_thread(event.update_thread_id)
            except DiscordRequestError as failure:
                if failure.discord_status == 403:
                    return progress(
                        error="Discord refused to delete the event thread (403). "
                        "Give the bot Manage Threads permission and retry cleanup."
                    )
                return failed(failure)
            event.update_thread_id = None
            db.commit()
        return progress()
