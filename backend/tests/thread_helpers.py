"""Shared event-thread setup without importing a collected test module."""

import time
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.discord.discord_api import DiscordAPI
from app.models import AssignmentPreference, Base, Event


@pytest.fixture
def thread_setup(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/threads.db")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(
            Event(
                id="event",
                title="Monday Games",
                guild_id="guild",
                channel_id="100",
                message_id="200",
                starts_at=time.time() + 86400,
                closes_at=time.time() + 3600,
                duration_hours=1,
                signup_mode="reactions",
                status="open",
                tables=[{"name": "One", "capacity": 1}],
                created_by="owner",
            )
        )
        db.add(
            AssignmentPreference(
                scope_key="user:owner",
                announce_table_changes=True,
                post_discord_updates_to_thread=True,
            )
        )
        db.commit()
    discord = Mock(spec=DiscordAPI)
    discord.event_thread.return_value = "200"
    discord.send_announcement.return_value = {"id": "300"}
    yield engine, discord
    engine.dispose()
