"""Give event threads their own neutral starter instead of the signup post."""

import hashlib
import time
import uuid

from fastapi import HTTPException
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.discord.discord_api import DiscordAPI
from app.discord.discord_format import clean
from app.models import Announcement, Event


def starter_message(
    engine: Engine, discord: DiscordAPI, event_id: str, channel_id: str
) -> str:
    # Use the existing durable outbox for nonce-based deduplication, uncertain
    # response reconciliation, retry leases, and archived-event message cleanup.
    with Session(engine) as db:
        event = db.scalar(select(Event).where(Event.id == event_id).with_for_update())
        if event is None or event.archived_at:
            raise HTTPException(409, "Event is unavailable for thread creation")
        row = db.scalar(
            select(Announcement).where(
                Announcement.event_id == event_id, Announcement.kind == "thread_starter"
            )
        )
        if row is None:
            now = time.time()
            row = Announcement(
                id=str(uuid.uuid4()),
                event_id=event_id,
                # Starters precede notices that need the thread to exist.
                part=-2,
                kind="thread_starter",
                channel_id=channel_id,
                payload={
                    "content": f"**{clean(event.title)}** — Event updates",
                    "allowed_mentions": {"parse": []},
                    "nonce": hashlib.sha256(
                        f"{event_id}:thread-starter".encode()
                    ).hexdigest()[:24],
                    "enforce_nonce": True,
                },
                created_at=now,
                next_attempt=now,
            )
            db.add(row)
        ready = row.state == "sent"
        db.commit()
    from app.discord.announcements import deliver_event

    if not ready:
        deliver_event(engine, discord, event_id, limit=1, kind="thread_starter")
    with Session(engine) as db:
        row = db.scalar(
            select(Announcement).where(
                Announcement.event_id == event_id, Announcement.kind == "thread_starter"
            )
        )
        if row and row.state == "sent" and row.message_id and not row.deleted_at:
            return row.message_id
    raise HTTPException(503, "Event thread starter has not been delivered to Discord")
