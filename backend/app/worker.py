"""Database-backed signup jobs; run separately from the API."""

import logging
import time

from fastapi import HTTPException
from sqlalchemy import Engine, and_, create_engine, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.discord_api import DiscordAPI
from app.models import Event, WorkerHeartbeat
from app.publication import publish_event
from app.scheduling import replenish

log = logging.getLogger(__name__)


def tick(engine: Engine, discord: DiscordAPI, config: Settings) -> None:
    replenish(engine, config.discord_guild_id)
    now = time.time()
    with Session(engine) as db:
        heartbeat_key = f"signup:{config.discord_guild_id}"
        heartbeat = db.get(WorkerHeartbeat, heartbeat_key)
        previous_tick = heartbeat.last_seen if heartbeat else None
        if heartbeat:
            heartbeat.last_seen = now
        else:
            db.add(WorkerHeartbeat(name=heartbeat_key, last_seen=now))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return
        db.execute(
            update(Event)
            .where(
                Event.guild_id == config.discord_guild_id,
                Event.status.in_(["publishing", "closing", "cancelling", "recovering"]),
                Event.operation_started_at < now - 120,
            )
            .values(
                status="needs_review",
                last_error="Worker interrupted; check Discord before recovery.",
            )
        )
        db.execute(
            update(Event)
            .where(
                Event.guild_id == config.discord_guild_id,
                Event.status == "scheduled",
                or_(
                    Event.signup_closes_at <= now,
                    and_(Event.signup_closes_at.is_(None), Event.closes_at <= now),
                ),
            )
            .values(
                status="needs_review",
                last_error="Signup window expired before publication.",
            )
        )
        db.commit()
        opening = list(
            db.scalars(
                select(Event.id).where(
                    Event.guild_id == config.discord_guild_id,
                    Event.status == "scheduled",
                    Event.opens_at <= now,
                    Event.signup_closes_at > now,
                )
            )
        )
        closing = list(
            db.scalars(
                select(Event.id).where(
                    Event.guild_id == config.discord_guild_id,
                    Event.status == "open",
                    or_(
                        Event.signup_closes_at <= now,
                        and_(Event.signup_closes_at.is_(None), Event.closes_at <= now),
                    ),
                )
            )
        )
    for event_id in opening:
        try:
            publish_event(engine, discord, config, event_id, scheduled=True)
        except HTTPException as failure:
            log.warning("Opening %s: %s", event_id, failure.detail)
    for event_id in closing:
        close_event(engine, discord, config, event_id, previous_tick)


def close_event(
    engine: Engine,
    discord: DiscordAPI,
    config: Settings,
    event_id: str,
    previous_tick: float | None = None,
) -> None:
    now = time.time()
    with Session(engine) as db:
        claimed = db.execute(
            update(Event)
            .where(
                Event.id == event_id,
                Event.guild_id == config.discord_guild_id,
                Event.status == "open",
                or_(
                    Event.signup_closes_at <= now,
                    and_(Event.signup_closes_at.is_(None), Event.closes_at <= now),
                ),
            )
            .values(status="closing", operation_started_at=now)
            .returning(Event.id)
        ).scalar_one_or_none()
        db.commit()
        if not claimed:
            return
        event = db.get(Event, event_id)
        assert event is not None
        try:
            deadline = event.signup_closes_at or event.closes_at
            if deadline is None or not event.message_id or event.closes_at is None:
                raise ValueError("Poll identifiers or deadlines are missing")
            healthy = (
                previous_tick is not None
                and previous_tick >= deadline - 15
                and now - previous_tick <= 15
            )
            if now > deadline and event.closes_at > deadline and not healthy:
                raise ValueError(
                    "Custom closing deadline was missed; later votes may be present"
                )
            if event.closes_at > now:
                discord.bot(
                    "POST",
                    f"/channels/{config.discord_channel_id}/polls/{event.message_id}/expire",
                )
            event.status = "closed"
            event.operation_started_at = None
            db.commit()
        except Exception as failure:
            db.rollback()
            db.execute(
                update(Event)
                .where(Event.id == event_id)
                .values(status="needs_review", last_error=str(failure))
            )
            db.commit()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config = Settings()
    engine = create_engine(config.database_url, pool_pre_ping=True)
    discord = DiscordAPI(config)
    while True:
        try:
            tick(engine, discord, config)
        except Exception:
            log.exception("Signup worker tick failed")
        time.sleep(5)


if __name__ == "__main__":
    main()
