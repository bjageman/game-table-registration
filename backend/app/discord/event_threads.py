"""Create event threads and retry durable RSVP membership additions."""

import hashlib
import logging
import time
import uuid
from collections.abc import Callable

from fastapi import HTTPException
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.discord.delivery import (
    UNCONFIRMED_DELIVERY,
    announcement_failure_values,
    claim_delivery,
    complete_delivery,
    resolve_message,
    save_delivery,
)
from app.discord.discord_api import DiscordAPI
from app.discord.discord_format import clean, sanitize_user_mentions
from app.models import (
    Announcement,
    Event,
    EventManagerSignup,
    EventThreadMember,
    EventWaitlistAddition,
    LotteryRun,
    TableSignup,
)
from app.settings.assignment_preferences import for_event


def ensure_thread_starter_message(
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
        row_id, ready = row.id, row.state == "sent"
        db.commit()
    if not ready:
        _deliver_thread_starter(engine, discord, row_id)
    with Session(engine) as db:
        row = db.scalar(
            select(Announcement).where(
                Announcement.event_id == event_id, Announcement.kind == "thread_starter"
            )
        )
        if row and row.state == "sent" and row.message_id and not row.deleted_at:
            return row.message_id
    raise HTTPException(503, "Event thread starter has not been delivered to Discord")


def _deliver_thread_starter(engine: Engine, discord: DiscordAPI, row_id: str) -> None:
    """Deliver only the starter, independent of assignment-post callbacks."""
    now = time.time()
    with Session(engine) as db:
        row = db.get(Announcement, row_id)
        if (
            row is None
            or row.kind != "thread_starter"
            or row.state not in ("pending", "sending")
            or row.next_attempt > now
        ):
            return
        event = db.get(Event, row.event_id)
        if event and event.archived_at:
            if row.unknown or row.state == "sending" or row.message_id:
                return
            row.state, row.deleted_at = "sent", now
            row.token = row.lease_until = None
            db.commit()
            return
        if row.state == "pending" and not row.unknown:
            row.payload = sanitize_user_mentions(row.payload)
        unknown = row.unknown or row.state == "sending"
        attempted_at = row.attempted_at or now
        token = claim_delivery(db, Announcement, row.id, now=now, attempted_at=now)
        db.commit()
        if token is None:
            return
        db.refresh(row)
        channel, payload, attempts = row.channel_id, row.payload, row.attempts
    try:
        message_id = resolve_message(
            discord, channel, payload, attempted_at, unknown=unknown
        )
        if message_id is None:
            raise RuntimeError(UNCONFIRMED_DELIVERY)
        with Session(engine) as db:
            complete_delivery(db, Announcement, row_id, token, message_id)
            db.commit()
    except Exception as failure:
        with Session(engine) as db:
            save_delivery(
                db,
                Announcement,
                row_id,
                token,
                **announcement_failure_values(
                    failure,
                    unknown=unknown,
                    sending=not unknown,
                    attempts=attempts,
                    now=time.time(),
                ),
            )
            db.commit()


def enabled(db: Session, event: Event) -> bool:
    preference = for_event(db, event)
    return bool(preference and preference.post_discord_updates_to_thread)


def queue_member(db: Session, event: Event, user_id: str) -> None:
    if not user_id.isascii() or not user_id.isdecimal() or not enabled(db, event):
        return
    if db.get(EventThreadMember, (event.id, user_id)) is None:
        try:
            with db.begin_nested():
                db.add(EventThreadMember(event_id=event.id, discord_id=user_id))
                db.flush()
        except IntegrityError:
            if db.get(EventThreadMember, (event.id, user_id)) is None:
                raise


def resolve_update_channel(
    engine: Engine,
    discord: DiscordAPI,
    event_id: str,
    fallback_channel_id: str | None = None,
) -> str:
    with Session(engine) as db:
        event = db.get(Event, event_id)
        if event is None:
            raise ValueError("Event has no Discord channel")
        channel_id = event.channel_id or fallback_channel_id
        if not channel_id:
            raise ValueError("Event has no Discord channel")
        if not enabled(db, event):
            return channel_id
        if event.update_thread_id:
            return event.update_thread_id
    message_id = ensure_thread_starter_message(engine, discord, event_id, channel_id)
    with Session(engine) as db:
        # Recheck after delivery. Concurrent attempts use the same starter ID,
        # so Discord cannot create a second message-based thread.
        event = db.get(Event, event_id)
        if event is None or event.archived_at or not enabled(db, event):
            raise ValueError("Event is unavailable for thread creation")
        if event.update_thread_id:
            return event.update_thread_id
        thread_id = discord.event_thread(channel_id, message_id, event.title)
        event.update_thread_id = thread_id
        db.commit()
        return thread_id


def synchronize_event(engine: Engine, discord: DiscordAPI, event_id: str) -> None:
    with Session(engine) as db:
        event = db.get(Event, event_id)
        if not event or event.archived_at or not enabled(db, event):
            return
    thread_id = resolve_update_channel(engine, discord, event_id)
    with Session(engine) as db:
        event = db.get(Event, event_id)
        if event is None:
            return
        users = set(
            db.scalars(
                select(TableSignup.discord_id).where(TableSignup.event_id == event_id)
            )
        )
        users.update(
            db.scalars(
                select(EventManagerSignup.discord_id).where(
                    EventManagerSignup.event_id == event_id,
                    EventManagerSignup.removed.is_(False),
                )
            )
        )
        users.update(
            db.scalars(
                select(EventWaitlistAddition.discord_id).where(
                    EventWaitlistAddition.event_id == event_id
                )
            )
        )
        run = db.get(LotteryRun, event_id)
        if run:
            users.update(player["id"] for player in run.snapshot["players"])
        # Backfill poll votes missed while the Gateway was disconnected.
        if (
            event.signup_mode == "poll"
            and event.status == "open"
            and event.message_id
            and (event.thread_sync_at or 0) < time.time() - 60
        ):
            for answer in event.answers or []:
                users.update(
                    player["id"]
                    for player in discord.voters(event.message_id, answer["answer_id"])
                )
            event.thread_sync_at = time.time()
        for user_id in users:
            queue_member(db, event, user_id)
        db.commit()
        pending = list(
            db.scalars(
                select(EventThreadMember.discord_id).where(
                    EventThreadMember.event_id == event_id,
                    EventThreadMember.added_at.is_(None),
                )
            )
        )
    for user_id in pending:
        try:
            discord.add_thread_member(thread_id, user_id)
            with Session(engine) as db:
                member = db.get(EventThreadMember, (event_id, user_id))
                if member:
                    member.added_at = time.time()
                    db.commit()
        except Exception:
            logging.getLogger(__name__).exception(
                "Could not add RSVP player to event thread %s", event_id
            )


def synchronize_due(
    engine: Engine, client_for: Callable[[str, str], DiscordAPI]
) -> None:
    with Session(engine) as db:
        events = [
            (event.id, event.guild_id, event.channel_id)
            for event in db.scalars(
                select(Event).where(
                    Event.status.in_(["open", "closing", "assigned"]),
                    Event.archived_at.is_(None),
                    Event.message_id.is_not(None),
                    Event.channel_id.is_not(None),
                    Event.starts_at > time.time(),
                )
            )
            if enabled(db, event)
        ]
    for event_id, guild, channel in events:
        try:
            synchronize_event(engine, client_for(guild, channel or ""), event_id)
        except Exception:
            logging.getLogger(__name__).exception(
                "Could not synchronize event thread %s", event_id
            )


def delete_event_thread(event: Event, discord: DiscordAPI) -> None:
    """Shared thread cleanup; keep the saved ID if Discord deletion fails."""
    if event.update_thread_id:
        discord.delete_thread(event.update_thread_id)
        event.update_thread_id = None
