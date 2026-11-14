"""Create server events once and keep their announcement links synchronized."""

import hashlib
import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.discord.discord_api import DiscordAPI, DiscordRequestError
from app.models import Announcement, DiscordScheduledEvent, Event


def announcement_url(event: Event, channel: str, message: str) -> str:
    return f"https://discord.com/channels/{event.guild_id}/{channel}/{message}"


def payload(event: Event, url: str) -> dict[str, Any]:
    end = event.ends_at or event.starts_at + 4 * 3600
    return {
        "name": event.title,
        "description": "\n\n".join(
            part for part in (event.location, event.description, url) if part
        ),
        "scheduled_start_time": datetime.fromtimestamp(
            event.starts_at, UTC
        ).isoformat(),
        "scheduled_end_time": datetime.fromtimestamp(end, UTC).isoformat(),
        "privacy_level": 2,
        "entity_type": 3,
        "channel_id": None,
        "entity_metadata": {"location": (event.location or "See announcement")[:100]},
    }


def synchronize_event(engine: Engine, discord: DiscordAPI, event_id: str) -> None:
    now = time.time()
    with Session(engine) as db:
        claimed = db.execute(
            update(DiscordScheduledEvent)
            .where(
                DiscordScheduledEvent.event_id == event_id,
                (DiscordScheduledEvent.checked_at.is_(None))
                | (DiscordScheduledEvent.checked_at < now - 60),
            )
            .values(checked_at=now)
            .returning(DiscordScheduledEvent.event_id)
        ).scalar_one_or_none()
        if claimed is None:
            return
        event = db.get(Event, event_id)
        record = db.get(DiscordScheduledEvent, event_id)
        if not event or not record or event.archived_at or not event.message_id:
            db.rollback()
            return
        signup_url = announcement_url(
            event,
            event.channel_id or discord.settings.discord_channel_id,
            event.message_id,
        )
        url = signup_url
        if event.status == "assigned":
            announcement = db.scalar(
                select(Announcement)
                .where(
                    Announcement.event_id == event_id,
                    Announcement.kind == "assignment",
                    Announcement.state == "sent",
                    Announcement.message_id.is_not(None),
                    Announcement.deleted_at.is_(None),
                )
                .order_by(Announcement.part)
                .limit(1)
            )
            if announcement:
                url = announcement_url(
                    event, announcement.channel_id, str(announcement.message_id)
                )
        desired = payload(event, url)
        digest = hashlib.sha256(
            json.dumps(desired, sort_keys=True).encode()
        ).hexdigest()
        discord_id, state, previous_hash = (
            record.discord_id,
            record.state,
            record.payload_hash,
        )
        guild_id = event.guild_id
        if not discord_id and state == "pending":
            record.state = "creating"
        db.commit()
    try:
        if not discord_id:
            if state in {"creating", "unknown"}:
                matches = [
                    row
                    for row in discord.scheduled_events()
                    if any(
                        link in (row.get("description") or "")
                        for link in (signup_url, url)
                    )
                ]
                if len(matches) != 1:
                    raise RuntimeError(
                        "Discord event creation could not be confirmed. "
                        "Check the server's Events list."
                    )
                discord_id = str(matches[0]["id"])
                discord.update_scheduled_event(discord_id, desired)
            else:
                created = discord.create_scheduled_event(desired)
                discord_id = str(created["id"])
        elif previous_hash != digest:
            discord.update_scheduled_event(discord_id, desired)
        with Session(engine) as db:
            record = db.get(DiscordScheduledEvent, event_id)
            if record:
                record.discord_id = discord_id
                record.payload_hash = digest
                record.state = "synced"
                record.error = None
                db.commit()
    except Exception as failure:
        with Session(engine) as db:
            record = db.get(DiscordScheduledEvent, event_id)
            if record:
                if discord_id:
                    record.discord_id = discord_id
                uncertain = not discord_id and (
                    state in {"creating", "unknown"}
                    or not isinstance(failure, DiscordRequestError)
                    or failure.ambiguous
                )
                record.state = "unknown" if uncertain else "pending"
                record.error = (
                    "Allow the bot to Create Events in Discord "
                    "to create the server event."
                    if isinstance(failure, DiscordRequestError)
                    and failure.discord_status == 403
                    else str(failure.detail)
                    if isinstance(failure, DiscordRequestError)
                    else str(failure)
                )[:500]
                db.commit()
        logging.getLogger(__name__).warning(
            "Server event sync failed for %s in guild %s", event_id, guild_id
        )


def synchronize_due(
    engine: Engine, client_for: Callable[[str, str], DiscordAPI]
) -> None:
    with Session(engine) as db:
        rows = list(
            db.execute(
                select(Event.id, Event.guild_id, Event.channel_id)
                .join(DiscordScheduledEvent, DiscordScheduledEvent.event_id == Event.id)
                .where(
                    Event.archived_at.is_(None),
                    Event.status.in_(["open", "review", "assigned"]),
                    Event.starts_at > time.time(),
                    (DiscordScheduledEvent.checked_at.is_(None))
                    | (DiscordScheduledEvent.checked_at < time.time() - 60),
                )
            )
        )
    for event_id, guild, channel in rows:
        synchronize_event(engine, client_for(guild, channel or ""), event_id)
