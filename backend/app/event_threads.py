"""Create event threads and retry durable RSVP membership additions."""

import logging
import time
from collections.abc import Callable

from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.assignment_preferences import for_event
from app.discord_api import DiscordAPI
from app.models import (
    Announcement,
    Event,
    EventManagerSignup,
    EventThreadMember,
    LotteryRun,
    TableSignup,
)


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


def update_channel(
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
        message_id = event.message_id
        if event.signup_deleted_at:
            message_id = db.scalar(
                select(Announcement.message_id)
                .where(
                    Announcement.event_id == event_id,
                    Announcement.kind == "assignment",
                    Announcement.message_id.is_not(None),
                    Announcement.deleted_at.is_(None),
                )
                .order_by(Announcement.part)
                .limit(1)
            )
        if not message_id:
            raise ValueError(
                "Publish signups or assignments before creating an event thread"
            )
        thread_id = discord.event_thread(channel_id, message_id, event.title)
        event.update_thread_id = thread_id
        db.commit()
        return thread_id


def synchronize_event(engine: Engine, discord: DiscordAPI, event_id: str) -> None:
    with Session(engine) as db:
        event = db.get(Event, event_id)
        if not event or event.archived_at or not enabled(db, event):
            return
    thread_id = update_channel(engine, discord, event_id)
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
