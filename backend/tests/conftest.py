"""Shared API integration fixtures."""

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import Base


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        _env_file=None,
        announcement_worker_enabled=False,
        database_url=os.getenv("TEST_DATABASE_URL", f"sqlite:///{tmp_path}/test.db"),
        discord_client_id="client",
        discord_signup_mode="poll",
        discord_gateway_enabled=False,
        discord_client_secret="secret",
        discord_bot_token="token",
        discord_guild_id="guild",
        discord_channel_id="channel",
        owner_discord_id="owner",
    )
    app = create_app(settings)
    Base.metadata.drop_all(app.state.engine)
    Base.metadata.create_all(app.state.engine)
    app.state.discord = Mock()
    app.state.discord.event_thread.return_value = "thread"
    app.state.discord.send_announcement.return_value = {"id": "announcement"}
    app.state.discord.identity.return_value = {"id": "owner", "username": "organizer"}
    app.state.discord.publish.return_value = {
        "id": "message",
        "poll": {
            "answers": [{"answer_id": 9}],
            "expiry": (datetime.now(UTC) + timedelta(hours=24)).isoformat(),
        },
    }
    with TestClient(app) as test_client:
        yield test_client
    assert app.state.engine.pool.checkedout() == 0
    app.state.engine.dispose()


@pytest.fixture
def promotion_db(tmp_path):
    """A saved draw with one seat and two eligible waitlisted players."""
    import time

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.lottery import VERSION
    from app.models import Announcement, AssignmentPreference, Event, LotteryRun

    engine = create_engine(
        os.getenv("TEST_DATABASE_URL", f"sqlite:///{tmp_path}/dm.db")
    )
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    people = [
        {"id": str(index), "name": name, "choices": ["Table A"], "weight": 5.0}
        for index, name in enumerate(["Alice", "Bob", "Carol"], 1)
    ]
    with Session(engine) as db:
        db.add(
            Event(
                id="event",
                guild_id="guild",
                channel_id="channel",
                message_id="signup",
                title="Game Night",
                starts_at=time.time() + 7200,
                duration_hours=24,
                tables=[{"name": "Table A", "capacity": 1}],
                status="assigned",
                created_by="owner",
            )
        )
        db.add(
            AssignmentPreference(
                scope_key="user:owner",
                dm_waitlist_promotions=True,
                announce_table_changes=False,
            )
        )
        db.flush()
        db.add(
            LotteryRun(
                event_id="event",
                version=VERSION,
                seed="saved-seed",
                created_by="owner",
                created_at=time.time(),
                snapshot={
                    "tables": [{"name": "Table A", "capacity": 1}],
                    "players": people,
                },
                result={
                    "order": ["1", "2", "3"],
                    "assignments": {"1": "Table A"},
                    "waitlist": ["2", "3"],
                    "tables": [
                        {
                            "name": "Table A",
                            "players": [people[0]],
                            "waitlist": people[1:],
                        }
                    ],
                },
            )
        )
        db.add(
            Announcement(
                id="assignment",
                event_id="event",
                part=0,
                state="sent",
                channel_id="channel",
                message_id="assignment-message",
                payload={"content": "Assignments"},
                created_at=time.time(),
                next_attempt=0,
            )
        )
        db.commit()
    yield engine
    assert engine.pool.checkedout() == 0
    engine.dispose()
