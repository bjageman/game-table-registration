import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DBSession

from app.config import Settings
from app.main import create_app, digest
from app.models import Base, Session


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        _env_file=None,
        database_url=os.getenv("TEST_DATABASE_URL", f"sqlite:///{tmp_path}/test.db"),
        discord_client_id="client",
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
    app.state.engine.dispose()


def login(client):
    response = client.get("/api/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
    response = client.get(
        f"/api/auth/callback?state={state}&code=code", follow_redirects=False
    )
    assert response.status_code == 307
    return {
        "Origin": "http://localhost:5180",
        "X-CSRF-Token": client.get("/api/me").json()["csrf"],
    }


def event_body():
    return {
        "title": "Friday games",
        "starts_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
        "duration_hours": 24,
        "tables": [{"name": "Clocktower", "capacity": 15}],
    }


def test_login_publish_and_duplicate_protection(client):
    headers = login(client)
    response = client.post("/api/events", headers=headers, json=event_body())
    assert response.status_code == 201
    event = response.json()
    path = f"/api/events/{event['id']}/publish"
    published = client.post(path, headers=headers)
    assert published.status_code == 200
    assert published.json()["status"] == "open"
    assert published.json()["discord_url"].endswith("/message")
    assert client.post(path, headers=headers).status_code == 409
    payload = client.app.state.discord.publish.call_args.args[0]
    assert payload["poll"]["allow_multiselect"] is True
    assert payload["allowed_mentions"] == {"parse": []}
    assert (
        payload["poll"]["answers"][0]["poll_media"]["text"] == "Clocktower · 15 seats"
    )
    assert client.app.state.discord.publish.call_count == 1


def test_auth_and_csrf(client):
    assert client.get("/api/events").status_code == 401
    headers = login(client)
    assert client.post("/api/events", json=event_body()).status_code == 403
    assert (
        client.post(
            "/api/events",
            headers={**headers, "Origin": "https://evil.test"},
            json=event_body(),
        ).status_code
        == 403
    )
    client.app.state.discord.authorize.side_effect = HTTPException(403, "Role removed")
    assert (
        client.post("/api/events", headers=headers, json=event_body()).status_code
        == 403
    )


def test_bad_state_and_replay(client):
    assert client.get("/api/auth/callback?code=x&state=x").status_code == 400
    response = client.get("/api/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
    assert (
        client.get(
            f"/api/auth/callback?code=x&state={state}", follow_redirects=False
        ).status_code
        == 307
    )
    client.cookies.set("oauth_state", state, path="/api")
    assert client.get(f"/api/auth/callback?code=x&state={state}").status_code == 400
    assert client.app.state.discord.identity.call_count == 1


def test_expired_session_and_logout(client):
    headers = login(client)
    assert client.post("/api/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/me").status_code == 401
    login(client)
    with DBSession(client.app.state.engine) as db:
        session = db.get(Session, digest(client.cookies.get("session")))
        session.expires = time.time() - 1
        db.commit()
    assert client.get("/api/me").status_code == 401


@pytest.mark.parametrize(
    "patch",
    [
        {"tables": []},
        {"tables": [{"name": "a", "capacity": 0}]},
        {"tables": [{"name": str(i)} for i in range(11)]},
        {"tables": [{"name": "a"}, {"name": "A"}]},
        {"starts_at": "2020-01-01T12:00:00+00:00"},
        {"starts_at": "2030-01-01T12:00:00"},
        {"duration_hours": 769},
        {"title": "   "},
        {"tables": [{"name": " "}]},
    ],
)
def test_validation(client, patch):
    assert (
        client.post(
            "/api/events", headers=login(client), json={**event_body(), **patch}
        ).status_code
        == 422
    )


def test_uncertain_publish_is_held(client):
    headers = login(client)
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    client.app.state.discord.publish.side_effect = TimeoutError()
    path = f"/api/events/{event['id']}/publish"
    assert client.post(path, headers=headers).status_code == 502
    assert client.get("/api/events").json()[0]["status"] == "needs_review"
    assert client.post(path, headers=headers).status_code == 409
    assert client.app.state.discord.publish.call_count == 1


def test_concurrent_publish_claim(client):
    headers = login(client)
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: (
                    client.post(
                        f"/api/events/{event['id']}/publish", headers=headers
                    ).status_code
                ),
                range(2),
            )
        )
    assert sorted(results) == [200, 409]
    assert client.app.state.discord.publish.call_count == 1


def test_health_and_configuration(client):
    assert client.get("/api/health/ready").status_code == 200
    assert client.get("/api/setup").json() == {"configured": True}


def test_edit_and_delete_unpublished_draft(client):
    headers = login(client)
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    path = f"/api/events/{event['id']}"
    body = {
        **event_body(),
        "title": "Updated games",
        "tables": [{"name": "New", "capacity": 123}],
    }
    assert client.put(path, json=body).status_code == 403
    saved = client.put(path, headers=headers, json=body)
    assert saved.status_code == 200
    assert saved.json()["title"] == "Updated games"
    assert saved.json()["tables"] == body["tables"]
    assert client.app.state.discord.publish.call_count == 0
    assert client.request("DELETE", path).status_code == 403
    assert client.delete(path, headers=headers).status_code == 204
    assert client.get("/api/events").json() == []
    assert client.post(path + "/publish", headers=headers).status_code == 404


@pytest.mark.parametrize("status", ["publishing", "needs_review", "cancelled"])
def test_published_events_cannot_be_edited_or_deleted(client, status):
    from app.models import Event

    headers = login(client)
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    with DBSession(client.app.state.engine) as db:
        row = db.get(Event, event["id"])
        row.status = status
        db.commit()
    path = f"/api/events/{event['id']}"
    assert client.put(path, headers=headers, json=event_body()).status_code == 409
    assert client.delete(path, headers=headers).status_code == 409
    assert client.get("/api/events").json()[0]["status"] == status


def test_signup_endpoint_is_authorized_and_scoped_to_guild(client):
    from app.models import Event

    assert client.get("/api/events/missing/signups").status_code == 401
    headers = login(client)
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    path = f"/api/events/{event['id']}/signups"
    result = client.get(path)
    assert result.status_code == 200
    assert all(t["players"] == [] for t in result.json())
    client.app.state.discord.table_signups.assert_not_called()
    with DBSession(client.app.state.engine) as db:
        row = db.get(Event, event["id"])
        row.message_id = "message"
        db.commit()
    players = [{"name": "A", "players": [{"id": "1", "name": "Mary"}]}]
    client.app.state.discord.table_signups.return_value = players
    assert client.get(path).json() == players
    with DBSession(client.app.state.engine) as db:
        db.get(Event, event["id"]).guild_id = "other-guild"
        db.commit()
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("delete_poll", [False, True])
def test_delete_open_signup_with_optional_discord_poll(client, delete_poll):
    headers = login(client)
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    path = f"/api/events/{event['id']}"
    assert client.post(path + "/publish", headers=headers).status_code == 200
    query = "?delete_poll=true" if delete_poll else ""
    assert client.delete(path + query).status_code == 403
    assert client.delete(path + query, headers=headers).status_code == 204
    assert client.get("/api/events").json() == []
    if delete_poll:
        client.app.state.discord.delete_poll.assert_called_once_with("message")
    else:
        client.app.state.discord.delete_poll.assert_not_called()


def test_failed_discord_deletion_preserves_signup_for_retry(client):
    headers = login(client)
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    path = f"/api/events/{event['id']}"
    client.post(path + "/publish", headers=headers)
    client.app.state.discord.delete_poll.side_effect = HTTPException(
        502, "Discord failed"
    )
    assert client.delete(path + "?delete_poll=true", headers=headers).status_code == 502
    assert client.get("/api/events").json()[0]["status"] == "open"
    client.app.state.discord.delete_poll.side_effect = None
    assert client.delete(path + "?delete_poll=true", headers=headers).status_code == 204


def test_cross_guild_signup_cannot_be_deleted(client):
    from app.models import Event

    headers = login(client)
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    with DBSession(client.app.state.engine) as db:
        row = db.get(Event, event["id"])
        row.guild_id = "other-guild"
        row.status = "open"
        row.message_id = "message"
        db.commit()
    assert (
        client.delete(
            f"/api/events/{event['id']}?delete_poll=true", headers=headers
        ).status_code
        == 409
    )
    client.app.state.discord.delete_poll.assert_not_called()


def test_player_profile_survives_event_and_poll_deletion(client):
    headers = login(client)
    client.app.state.discord.bot.return_value = {
        "username": "mary",
        "global_name": "Mary",
    }
    path = "/api/players/123"
    assert client.get(path).json() == {
        "discord_id": "123",
        "discord_name": "Mary",
        "real_name": "",
        "weighting": 1.0,
    }
    assert client.put(path, json={"real_name": "Mary Smith"}).status_code == 403
    saved = client.put(path, headers=headers, json={"real_name": " Mary Smith "})
    assert saved.status_code == 200
    assert saved.json()["real_name"] == "Mary Smith"
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    event_path = f"/api/events/{event['id']}"
    client.post(event_path + "/publish", headers=headers)
    assert (
        client.delete(event_path + "?delete_poll=true", headers=headers).status_code
        == 204
    )
    assert client.get(path).json() == saved.json()
    client.app.state.discord.delete_poll.assert_called_once_with("message")
    client.app.state.discord.bot.reset_mock()
    assert client.get(path).json()["discord_name"] == "Mary"
    client.app.state.discord.bot.assert_not_called()


def test_player_profiles_are_scoped_to_guild_and_weighting_is_read_only(client):
    from app.models import PlayerProfile

    headers = login(client)
    client.app.state.discord.bot.return_value = {"username": "mary"}
    with DBSession(client.app.state.engine) as db:
        db.add(
            PlayerProfile(
                guild_id="other",
                discord_id="123",
                discord_name="Other",
                real_name="Private",
                weighting=2.0,
            )
        )
        db.commit()
    assert client.get("/api/players/123").json()["real_name"] == ""
    assert (
        client.put(
            "/api/players/123",
            headers=headers,
            json={"real_name": "Mary", "weighting": 5},
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/api/players/123", headers=headers, json={"real_name": "x" * 101}
        ).status_code
        == 422
    )
    assert client.get("/api/players/invalid").status_code == 422
    saved = client.put("/api/players/123", headers=headers, json={"real_name": "Mary"})
    assert saved.json()["weighting"] == 1.0
    with DBSession(client.app.state.engine) as db:
        assert db.get(PlayerProfile, ("other", "123")).real_name == "Private"
