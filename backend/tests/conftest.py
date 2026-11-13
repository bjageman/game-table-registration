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
