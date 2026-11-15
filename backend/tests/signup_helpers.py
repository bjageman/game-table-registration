"""Shared Discord signup fixtures and publication workflows."""

import os
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from flow_helpers import event_body, login, set_assignment_review
from sqlalchemy.orm import Session

from app.config import Settings
from app.main import create_app
from app.models import Base, Event


@pytest.fixture
def custom_client(tmp_path):
    settings = Settings(
        _env_file=None,
        announcement_worker_enabled=False,
        database_url=os.getenv("TEST_DATABASE_URL", f"sqlite:///{tmp_path}/custom.db"),
        discord_client_id="123",
        discord_client_secret="secret",
        discord_bot_token="token",
        discord_gateway_enabled=False,
        discord_guild_id="guild",
        discord_channel_id="channel",
        owner_discord_id="owner",
    )
    app = create_app(settings)
    Base.metadata.drop_all(app.state.engine)
    Base.metadata.create_all(app.state.engine)
    app.state.discord = Mock()
    app.state.discord.identity.return_value = {"id": "owner", "username": "organizer"}
    app.state.discord.publish.return_value = {"id": "message"}
    app.state.discord.send_announcement.return_value = {"id": "announcement"}
    with TestClient(app) as client:
        yield client, None, settings
    app.state.engine.dispose()


def publish(custom_client, *, reaction=False, review=False):
    client, _, _ = custom_client
    headers = login(client)
    set_assignment_review(client, headers, review)
    body = {
        **event_body(),
        "tables": [{"name": "A", "capacity": 1}, {"name": "B", "capacity": 1}],
    }
    event = client.post("/api/events", json=body, headers=headers).json()
    result = client.post(f"/api/events/{event['id']}/publish", headers=headers)
    assert result.status_code == 200, result.text
    saved = result.json()
    if not reaction:
        # Existing menu-based events remain supported after changing new posts
        # to reactions. Exercise that compatibility path in these tests.
        with Session(client.app.state.engine) as db:
            db.get(Event, saved["id"]).signup_mode = "custom"
            db.commit()
        saved["signup_mode"] = "custom"
    return headers, saved, f"/api/events/{event['id']}"
