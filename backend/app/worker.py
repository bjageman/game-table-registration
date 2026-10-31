"""Database-backed signup jobs; run separately from the API."""

import logging
import time

from fastapi import HTTPException
from sqlalchemy import Engine, create_engine, select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.discord_api import DiscordAPI
from app.models import Event
from app.publication import publish_event

log = logging.getLogger(__name__)


def tick(engine: Engine, discord: DiscordAPI, config: Settings) -> None:
    now = time.time()
    with Session(engine) as db:
        db.execute(
            update(Event)
            .where(
                Event.guild_id == config.discord_guild_id,
                Event.status.in_(["publishing", "closing"]),
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
                Event.signup_closes_at <= now,
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
                    Event.signup_closes_at <= now,
                )
            )
        )
    for event_id in opening:
        try:
            publish_event(engine, discord, config, event_id, scheduled=True)
        except HTTPException as failure:
            log.warning("Opening %s: %s", event_id, failure.detail)
    for event_id in closing:
        close_event(engine, discord, config, event_id)


def close_event(
    engine: Engine, discord: DiscordAPI, config: Settings, event_id: str
) -> None:
    now = time.time()
    with Session(engine) as db:
        claimed = db.execute(
            update(Event)
            .where(
                Event.id == event_id,
                Event.guild_id == config.discord_guild_id,
                Event.status == "open",
                Event.signup_closes_at <= now,
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
            deadline = event.signup_closes_at
            if deadline is None or not event.message_id or event.closes_at is None:
                raise ValueError("Poll identifiers or deadlines are missing")
            if now > deadline + 60 and event.closes_at > deadline + 60:
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
