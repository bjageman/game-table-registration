"""Schedule one durable warning per event while signups are still open."""

import time
import uuid
from typing import Any, Protocol

from sqlalchemy import Engine, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.discord_format import clean
from app.models import Announcement, Event

DEFAULT_WARNING_MESSAGE = "Signups close soon! Don't forget to sign up."


class WarningSettings(Protocol):
    post_warning_message: bool
    warning_hours_before_close: int
    warning_message: str


def settings(source: WarningSettings) -> dict[str, Any]:
    return {
        "post_warning_message": source.post_warning_message,
        "warning_hours_before_close": source.warning_hours_before_close,
        "warning_message": source.warning_message,
    }


def can_send(event: Event | None, now: float) -> bool:
    return bool(
        event
        and event.post_warning_message
        and event.status == "open"
        and not event.archived_at
        and event.closes_at
        and event.closes_at > now
        and event.message_id
        and event.channel_id
    )


def payload(event: Event) -> dict[str, Any]:
    assert event.closes_at is not None
    deadline = int(event.closes_at)
    url = f"https://discord.com/channels/{event.guild_id}/{event.channel_id}/{event.message_id}"
    message = event.warning_message.strip() or DEFAULT_WARNING_MESSAGE
    heading = f"**{clean(event.title)}**\n"
    footer = (
        f"\nSignups close <t:{deadline}:R> (<t:{deadline}:f>).\n[Sign up here]({url})"
    )
    return {
        "content": heading + message[: 2000 - len(heading) - len(footer)] + footer,
        "allowed_mentions": {"parse": []},
        "nonce": uuid.uuid5(uuid.NAMESPACE_URL, f"{event.id}:signup-warning").hex[:24],
        "enforce_nonce": True,
    }


def enqueue_due(engine: Engine) -> None:
    now = time.time()
    with Session(engine) as db:
        ids = list(
            db.scalars(
                select(Event.id)
                .where(
                    Event.post_warning_message.is_(True),
                    Event.status == "open",
                    Event.archived_at.is_(None),
                    Event.closes_at > now,
                    Event.closes_at - Event.warning_hours_before_close * 3600 <= now,
                    Event.message_id.is_not(None),
                    Event.channel_id.is_not(None),
                )
                .limit(100)
            )
        )
    for event_id in ids:
        with Session(engine) as db:
            # Serialize enqueueing with closing, deletion, and other workers.
            claimed = db.execute(
                update(Event)
                .where(
                    Event.id == event_id,
                    Event.status == "open",
                    Event.post_warning_message.is_(True),
                    Event.archived_at.is_(None),
                    Event.closes_at > now,
                )
                .values(status=Event.status)
                .returning(Event.id)
            ).scalar_one_or_none()
            if claimed is None:
                continue
            event = db.get(Event, event_id)
            if not can_send(event, now):
                continue
            assert event is not None and event.channel_id is not None
            row_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{event_id}:signup-warning"))
            if db.get(Announcement, row_id) is not None:
                continue
            db.add(
                Announcement(
                    id=row_id,
                    event_id=event_id,
                    part=-1,
                    kind="warning",
                    channel_id=event.channel_id,
                    payload=payload(event),
                    state="pending",
                    created_at=now,
                    next_attempt=now,
                )
            )
            try:
                db.commit()
            except IntegrityError:
                # A concurrent worker may already have queued this same warning.
                db.rollback()
