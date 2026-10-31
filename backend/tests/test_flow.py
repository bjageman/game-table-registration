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


@pytest.mark.parametrize("status", ["publishing", "open", "needs_review", "cancelled"])
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


def test_explicit_signup_window(client):
    headers = login(client)
    now = datetime.now(UTC)
    body = {
        **event_body(),
        "timezone": "America/New_York",
        "opens_at": (now + timedelta(days=1)).isoformat(),
        "signup_closes_at": (now + timedelta(days=2)).isoformat(),
    }
    response = client.post("/api/events", headers=headers, json=body)
    assert response.status_code == 201
    assert response.json()["timezone"] == "America/New_York"
    assert response.json()["opens_at"] < response.json()["signup_closes_at"]
    assert (
        client.post(
            f"/api/events/{response.json()['id']}/publish", headers=headers
        ).status_code
        == 409
    )
    body["signup_closes_at"] = body["opens_at"]
    assert client.post("/api/events", headers=headers, json=body).status_code == 422
    body["timezone"] = "Not/AZone"
    assert client.post("/api/events", headers=headers, json=body).status_code == 422


def schedule_body():
    return {
        "title": "Weekly games",
        "timezone": "UTC",
        "first_date": (datetime.now(UTC) + timedelta(days=14)).date().isoformat(),
        "event_time": "19:00",
        "opening_days_before": 7,
        "opening_time": "12:00",
        "closing_days_before": 1,
        "closing_time": "12:00",
        "tables": [{"name": "A", "capacity": 15}],
    }


def test_schedule_edits_preserve_published_and_overridden_occurrences(client):
    from app.models import Event

    headers = login(client)
    body = schedule_body()
    assert client.post("/api/schedules", json=body).status_code == 403
    schedule = client.post("/api/schedules", headers=headers, json=body).json()
    events = client.get("/api/events").json()
    assert len(events) == 8
    first, second, third = events[:3]
    with DBSession(client.app.state.engine) as db:
        db.get(Event, first["id"]).status = "open"
        db.commit()
    override = {
        **event_body(),
        "title": "Special week",
        "opens_at": datetime.fromtimestamp(second["opens_at"], UTC).isoformat(),
        "signup_closes_at": datetime.fromtimestamp(
            second["signup_closes_at"], UTC
        ).isoformat(),
        "starts_at": datetime.fromtimestamp(second["starts_at"], UTC).isoformat(),
    }
    assert (
        client.put(
            f"/api/events/{second['id']}", headers=headers, json=override
        ).status_code
        == 200
    )
    assert (
        client.post(f"/api/events/{third['id']}/cancel", headers=headers).status_code
        == 200
    )
    changed = {
        **body,
        "revision": schedule["revision"],
        "title": "New weekly games",
        "tables": [{"name": "B", "capacity": 20}],
    }
    preview = client.post(
        f"/api/schedules/{schedule['id']}/preview", headers=headers, json=changed
    ).json()
    assert sum(r["action"] == "preserved" for r in preview) == 3
    saved = client.put(
        f"/api/schedules/{schedule['id']}", headers=headers, json=changed
    )
    assert saved.status_code == 200
    assert (
        client.put(
            f"/api/schedules/{schedule['id']}", headers=headers, json=changed
        ).status_code
        == 409
    )
    updated = client.get("/api/events").json()
    by_id = {e["id"]: e for e in updated}
    assert by_id[first["id"]]["tables"] == first["tables"]
    assert by_id[second["id"]]["title"] == "Special week"
    assert by_id[third["id"]]["status"] == "cancelled"
    assert updated[-1]["tables"] == [{"name": "B", "capacity": 20}]
    revision = saved.json()["revision"]
    path = f"/api/schedules/{schedule['id']}/active"
    paused = client.post(
        path, headers=headers, json={"active": False, "revision": revision}
    )
    assert paused.status_code == 200
    assert (
        client.post(
            path, headers=headers, json={"active": False, "revision": revision}
        ).status_code
        == 409
    )
    assert {e["status"] for e in client.get("/api/events").json()} == {
        "open",
        "paused",
        "cancelled",
    }
