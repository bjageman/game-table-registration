"""Persist public table-change messages alongside assignment mutations."""

import hashlib
import uuid
from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.discord.discord_format import is_discord_user_id
from app.models import Announcement, Event
from app.settings.assignment_preferences import announce_changes


def enqueue_table_change(
    db: Session,
    event: Event,
    content: str,
    recipients: Iterable[str],
    *,
    nonce_key: str,
    created_at: float,
    channel_id: str | None = None,
) -> None:
    """The caller holds the assignment mutation lock and commits the outbox."""
    if event.status != "assigned" or not announce_changes(db, event):
        return
    channel = (
        event.channel_id
        or channel_id
        or db.scalar(
            select(Announcement.channel_id)
            .where(Announcement.event_id == event.id)
            .order_by(Announcement.part)
            .limit(1)
        )
    )
    if not channel:
        return
    part = db.scalar(
        select(func.max(Announcement.part)).where(Announcement.event_id == event.id)
    )
    db.add(
        Announcement(
            id=str(uuid.uuid4()),
            event_id=event.id,
            part=(part if part is not None else -1) + 1,
            kind="promotion",
            channel_id=channel,
            payload={
                "content": content,
                "allowed_mentions": {
                    "parse": [],
                    "users": [pid for pid in recipients if is_discord_user_id(pid)],
                },
                "nonce": hashlib.sha256(nonce_key.encode()).hexdigest()[:24],
                "enforce_nonce": True,
            },
            created_at=created_at,
            next_attempt=created_at,
        )
    )
