import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Base, Event
from app.worker import tick


def setup(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/jobs.db")
    Base.metadata.create_all(engine)
    now = time.time()
    with Session(engine) as db:
        db.add(
            Event(
                id="event",
                guild_id="guild",
                title="Games",
                starts_at=now + 10000,
                opens_at=now - 5,
                signup_closes_at=now + 3600,
                duration_hours=1,
                tables=[{"name": "A", "capacity": 15}],
                status="scheduled",
                created_by="owner",
            )
        )
        db.commit()
    return engine, Settings(
        _env_file=None, discord_guild_id="guild", discord_channel_id="channel"
    )


def test_workers_publish_once(tmp_path):
    from datetime import UTC, datetime, timedelta

    engine, config = setup(tmp_path)
    discord = Mock()
    discord.publish.return_value = {
        "id": "message",
        "poll": {
            "answers": [],
            "expiry": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        },
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: tick(engine, discord, config), range(2)))
    tick(engine, discord, config)
    assert discord.publish.call_count == 1
    with Session(engine) as db:
        assert db.get(Event, "event").status == "open"


def test_expired_jobs_do_not_publish(tmp_path):
    engine, config = setup(tmp_path)
    with Session(engine) as db:
        db.get(Event, "event").signup_closes_at = time.time() - 5
        db.commit()
    discord = Mock()
    tick(engine, discord, config)
    discord.publish.assert_not_called()
    with Session(engine) as db:
        assert db.get(Event, "event").status == "needs_review"


def test_missed_custom_close_is_held(tmp_path):
    engine, config = setup(tmp_path)
    with Session(engine) as db:
        event = db.get(Event, "event")
        event.status = "open"
        event.message_id = "message"
        event.signup_closes_at = time.time() - 120
        event.closes_at = time.time() + 3600
        db.commit()
    discord = Mock()
    tick(engine, discord, config)
    discord.bot.assert_not_called()
    with Session(engine) as db:
        assert db.get(Event, "event").status == "needs_review"
