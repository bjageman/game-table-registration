"""Persist numbered reaction selections and track recoverable Gateway gaps."""

import asyncio
import threading
import time
import weakref
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Engine, delete, select, update
from sqlalchemy.orm import Session

from app.discord.event_messages import EMOJIS, build_signup_message
from app.discord.event_threads import queue_member
from app.models import Event, TableSignup

GAP = (
    "Reaction signups need synchronization. Keep the bot connected before the deadline."
)


MessageKey = tuple[str, str, str]


class ReactionQueue:
    """Coordinate received Gateway work with synchronous signup closing."""

    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.pending: dict[MessageKey, int] = {}
        self.closing: set[MessageKey] = set()
        self.connection_changes = 0
        self.waiters: dict[
            MessageKey, list[tuple[asyncio.AbstractEventLoop, asyncio.Future[None]]]
        ] = {}

    @contextmanager
    def track(self, key: MessageKey) -> Iterator[bool]:
        with self.condition:
            accepted = key not in self.closing
            if accepted:
                self.pending[key] = self.pending.get(key, 0) + 1
        try:
            yield accepted
        finally:
            if accepted:
                with self.condition:
                    self.pending[key] -= 1
                    if not self.pending[key]:
                        del self.pending[key]
                    self.condition.notify_all()

    @contextmanager
    def connection_change(self) -> Iterator[None]:
        with self.condition:
            self.connection_changes += 1
        try:
            yield
        finally:
            with self.condition:
                self.connection_changes -= 1
                self.condition.notify_all()

    async def wait_until_open(self, key: MessageKey) -> None:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()
        with self.condition:
            if key not in self.closing:
                return
            self.waiters.setdefault(key, []).append((loop, future))
        await future

    @contextmanager
    def freeze(self, key: MessageKey, timeout: float = 60) -> Iterator[None]:
        with self.condition:
            if key in self.closing:
                raise HTTPException(
                    409, "Reaction signup closing is already in progress."
                )
            self.closing.add(key)
        try:
            with self.condition:
                if not self.condition.wait_for(
                    lambda: key not in self.pending and not self.connection_changes,
                    timeout,
                ):
                    raise HTTPException(
                        409,
                        "Reactions are still processing; retry closing shortly.",
                    )
            yield
        finally:
            with self.condition:
                self.closing.remove(key)
                waiters = self.waiters.pop(key, [])
            for loop, future in waiters:

                def resume(target: asyncio.Future[None] = future) -> None:
                    if not target.done():
                        target.set_result(None)

                try:
                    loop.call_soon_threadsafe(resume)
                except RuntimeError:
                    pass  # The Gateway loop shut down while closing finished.


_queues: weakref.WeakKeyDictionary[Engine, ReactionQueue] = weakref.WeakKeyDictionary()
_queues_lock = threading.Lock()


def reaction_queue(engine: Engine) -> ReactionQueue:
    with _queues_lock:
        if engine not in _queues:
            _queues[engine] = ReactionQueue()
        return _queues[engine]


def publication(
    event: Event, closes_at: float | None, include_roster: bool = True
) -> dict[str, Any]:
    return {
        **build_signup_message(event, "reactions", closes_at, include_roster),
        "allowed_mentions": {"parse": []},
    }


def event_for(engine: Engine, guild: str, channel: str, message: str) -> str | None:
    with Session(engine) as db:
        return db.scalar(
            select(Event.id).where(
                Event.guild_id == guild,
                Event.channel_id == channel,
                Event.message_id == message,
                Event.signup_mode == "reactions",
                Event.status == "open",
            )
        )


def change(
    engine: Engine,
    event_id: str,
    emoji: str | None,
    user_id: str | None,
    name: str,
    added: bool,
    observed_at: float,
) -> None:
    with Session(engine) as db:
        claimed = db.execute(
            update(Event)
            .where(
                Event.id == event_id,
                Event.status == "open",
                Event.signup_mode == "reactions",
                (Event.closes_at.is_(None)) | (Event.closes_at > observed_at),
            )
            .values(status=Event.status, signup_roster_checked_at=None)
            .returning(Event.id)
        ).scalar_one_or_none()
        if claimed is None:
            return
        event = db.get(Event, event_id)
        assert event is not None
        if emoji is not None and emoji not in EMOJIS[: len(event.tables)]:
            return
        table = event.tables[EMOJIS.index(emoji)]["name"] if emoji else None
        if user_id is None:
            rows = list(
                db.scalars(select(TableSignup).where(TableSignup.event_id == event_id))
            )
        else:
            row = db.get(TableSignup, (event_id, user_id))
            rows = [row] if row else []
            if added and not row:
                row = TableSignup(
                    event_id=event_id,
                    discord_id=user_id,
                    discord_name=name[:100],
                    choices=[],
                )
                db.add(row)
                rows = [row]
        for row in rows:
            choices = set(row.choices)
            if added and table:
                choices.add(table)
                row.discord_name = name[:100]
            elif table:
                choices.discard(table)
            else:
                choices.clear()
            row.choices = [t["name"] for t in event.tables if t["name"] in choices]
            if not row.choices:
                db.delete(row)
        if added and user_id and table:
            queue_member(db, event, user_id)
        db.commit()


def mark_gap(engine: Engine) -> None:
    with Session(engine) as db:
        db.execute(
            update(Event)
            .where(
                Event.signup_mode == "reactions",
                Event.status == "open",
                (Event.closes_at.is_(None))
                | (Event.reaction_checkpoint.is_(None))
                | (Event.reaction_checkpoint < Event.closes_at),
            )
            .values(reaction_error=GAP)
        )
        db.commit()


def pending(engine: Engine) -> list[dict[str, Any]]:
    with Session(engine) as db:
        return [
            {
                "id": e.id,
                "guild": e.guild_id,
                "channel": e.channel_id,
                "message": e.message_id,
                "tables": e.tables,
                "deadline": e.closes_at,
                "sync": e.reaction_checkpoint is None or bool(e.reaction_error),
            }
            for e in db.scalars(
                select(Event).where(
                    Event.signup_mode == "reactions",
                    Event.status == "open",
                    (Event.closes_at.is_(None))
                    | (Event.reaction_checkpoint.is_(None))
                    | (Event.reaction_checkpoint < Event.closes_at),
                )
            )
        ]


def replace(
    engine: Engine, event_id: str, participants: list[dict[str, Any]], started: float
) -> bool:
    with Session(engine) as db:
        changed = db.execute(
            update(Event)
            .where(
                Event.id == event_id,
                Event.status == "open",
                (Event.closes_at.is_(None)) | (Event.closes_at > time.time()),
                Event.signup_mode == "reactions",
            )
            .values(
                reaction_checkpoint=started,
                reaction_error=None,
                signup_roster_checked_at=None,
            )
            .returning(Event.id)
        ).scalar_one_or_none()
        if not changed:
            return False
        db.execute(delete(TableSignup).where(TableSignup.event_id == event_id))
        event = db.get(Event, event_id)
        assert event is not None
        for player in participants:
            queue_member(db, event, player["id"])
            db.add(
                TableSignup(
                    event_id=event_id,
                    discord_id=player["id"],
                    discord_name=player["name"][:100],
                    choices=player["choices"],
                )
            )
        db.commit()
        return True


def checkpoint(engine: Engine, event_id: str) -> None:
    with Session(engine) as db:
        event = db.get(Event, event_id)
        if not event or event.reaction_error or event.reaction_checkpoint is None:
            return
        db.execute(
            update(Event)
            .where(
                Event.id == event_id,
                Event.status == "open",
                Event.reaction_error.is_(None),
            )
            .values(
                reaction_checkpoint=min(
                    time.time(),
                    event.closes_at if event.closes_at is not None else time.time(),
                )
            )
        )
        db.commit()
