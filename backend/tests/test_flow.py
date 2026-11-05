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


def test_organizations_share_selected_events_and_enforce_member_roles(client):
    owner_headers = login(client)
    personal = client.post(
        "/api/events", headers=owner_headers, json=event_body()
    ).json()
    organization = client.post(
        "/api/organizations", headers=owner_headers, json={"name": "Friday Crew"}
    )
    assert organization.status_code == 201
    org_id = organization.json()["id"]
    assert (
        client.put(
            "/api/organizations/selection",
            headers=owner_headers,
            json={"organization_id": org_id},
        ).status_code
        == 200
    )
    shared = client.post("/api/events", headers=owner_headers, json=event_body()).json()
    assert [event["id"] for event in client.get("/api/events").json()] == [shared["id"]]

    client.app.state.discord.identity.return_value = {
        "id": "second",
        "username": "Second",
    }
    second_headers = login(client)
    assert client.get("/api/events").json() == []
    client.app.state.discord.identity.return_value = {
        "id": "owner",
        "username": "organizer",
    }
    owner_headers = login(client)
    assert (
        client.put(
            f"/api/organizations/{org_id}/members/second",
            headers=owner_headers,
            json={"user_id": "second", "role": "user"},
        ).status_code
        == 200
    )

    client.app.state.discord.identity.return_value = {
        "id": "second",
        "username": "Second",
    }
    second_headers = login(client)
    assert (
        client.put(
            "/api/organizations/selection",
            headers=second_headers,
            json={"organization_id": org_id},
        ).status_code
        == 200
    )
    assert [event["id"] for event in client.get("/api/events").json()] == [shared["id"]]
    assert (
        client.post(
            "/api/events", headers=second_headers, json=event_body()
        ).status_code
        == 403
    )
    client.app.state.discord.authorize.side_effect = HTTPException(
        403, "Not a Discord manager"
    )
    assert [event["id"] for event in client.get("/api/events").json()] == [shared["id"]]
    client.app.state.discord.authorize.side_effect = None
    assert client.get(f"/api/events/{personal['id']}/signups").status_code == 404
    client.app.state.discord.identity.return_value = {
        "id": "owner",
        "username": "organizer",
    }
    owner_headers = login(client)
    assert (
        client.post(
            "/api/organizations", headers=owner_headers, json={"name": "FRIDAY CREW"}
        ).status_code
        == 409
    )
    assert (
        client.put(
            f"/api/organizations/{org_id}/members/second",
            headers=owner_headers,
            json={"user_id": "second", "role": "editor"},
        ).status_code
        == 200
    )
    client.app.state.discord.identity.return_value = {
        "id": "second",
        "username": "Second",
    }
    second_headers = login(client)
    assert (
        client.post(
            "/api/events", headers=second_headers, json=event_body()
        ).status_code
        == 201
    )
    assert (
        client.delete(
            f"/api/organizations/{org_id}/members/me", headers=second_headers
        ).status_code
        == 204
    )
    assert client.get("/api/events").json() == []
    client.app.state.discord.identity.return_value = {
        "id": "owner",
        "username": "organizer",
    }
    owner_headers = login(client)
    assert (
        client.delete(f"/api/organizations/{org_id}", headers=owner_headers).status_code
        == 204
    )
    assert {event["id"] for event in client.get("/api/events").json()} == {
        personal["id"],
        shared["id"],
    }


def event_body():
    return {
        "title": "Friday games",
        "starts_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
        "duration_hours": 24,
        "tables": [{"name": "Clocktower", "capacity": 15}],
    }


def test_recurring_events_schedule_cancel_and_stop(client):
    headers = login(client)
    body = {
        **event_body(),
        "frequency": "weekly",
        "time_zone": "America/New_York",
        "opens_before_hours": 72,
        "closes_before_hours": 24,
    }
    created = client.post("/api/recurring-series", headers=headers, json=body)
    assert created.status_code == 201, created.text
    series_id = created.json()["id"]
    scheduled = [
        row for row in client.get("/api/events").json() if row["series_id"] == series_id
    ]
    assert len(scheduled) == 4
    assert all(row["status"] == "scheduled" for row in scheduled)
    assert all(row["duration_hours"] == 48 for row in scheduled)
    assert scheduled[0]["scheduled_publish_at"] == scheduled[0]["starts_at"] - 72 * 3600
    assert (
        client.post(
            f"/api/events/{scheduled[0]['id']}/cancel-scheduled", headers=headers
        ).status_code
        == 204
    )
    replacement = [
        row for row in client.get("/api/events").json() if row["series_id"] == series_id
    ]
    assert len(replacement) == 4
    assert scheduled[0]["id"] not in {row["id"] for row in replacement}
    assert (
        client.post(
            f"/api/recurring-series/{series_id}/stop", headers=headers
        ).status_code
        == 204
    )
    assert not [
        row for row in client.get("/api/events").json() if row["series_id"] == series_id
    ]


def test_due_recurring_event_is_published_once_by_worker(tmp_path):
    from sqlalchemy import update

    from app.models import Event

    settings = Settings(
        _env_file=None,
        announcement_worker_enabled=True,
        database_url=f"sqlite:///{tmp_path}/scheduled.db",
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
    Base.metadata.create_all(app.state.engine)
    app.state.discord = Mock()
    app.state.discord.identity.return_value = {"id": "owner", "username": "organizer"}
    app.state.discord.publish.return_value = {
        "id": "message",
        "poll": {
            "answers": [{"answer_id": 9}],
            "expiry": (datetime.now(UTC) + timedelta(hours=48)).isoformat(),
        },
    }
    with TestClient(app) as test_client:
        headers = login(test_client)
        body = {
            **event_body(),
            "frequency": "weekly",
            "time_zone": "America/New_York",
            "opens_before_hours": 72,
            "closes_before_hours": 24,
        }
        assert (
            test_client.post(
                "/api/recurring-series", headers=headers, json=body
            ).status_code
            == 201
        )
        first = test_client.get("/api/events").json()[0]
        with DBSession(app.state.engine) as db:
            db.execute(
                update(Event)
                .where(Event.id == first["id"])
                .values(scheduled_publish_at=time.time() - 1)
            )
            db.commit()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if test_client.get("/api/events").json()[0]["status"] == "open":
                break
            time.sleep(0.2)
        else:
            pytest.fail("Scheduled event was not published")
        assert app.state.discord.publish.call_count == 1
    app.state.engine.dispose()


def test_templates_save_reusable_details_without_an_event_date_and_are_private(client):
    headers = login(client)
    body = {
        "title": "Friday games",
        "description": "Bring friends",
        "location": "Queen & Rook",
        "duration_hours": 24,
        "tables": [{"name": "Clocktower", "capacity": 15}],
    }
    assert client.get("/api/templates").json() == []
    assert client.post("/api/templates", json=body).status_code == 403
    created = client.post("/api/templates", headers=headers, json=body)
    assert created.status_code == 201
    assert created.json() == {"id": created.json()["id"], **body}
    assert client.get("/api/templates").json() == [created.json()]
    assert client.get("/api/events").json() == []
    assert (
        client.post(
            "/api/templates",
            headers=headers,
            json={**body, "tables": [body["tables"][0]] * 2},
        ).status_code
        == 422
    )
    client.app.state.discord.identity.return_value = {
        "id": "second",
        "username": "Second",
    }
    login(client)
    assert client.get("/api/templates").json() == []
    client.app.state.discord.identity.return_value = {
        "id": "owner",
        "username": "organizer",
    }
    login(client)
    assert client.get("/api/templates").json() == [created.json()]


def test_login_publish_and_duplicate_protection(client):
    headers = login(client)
    response = client.post(
        "/api/events",
        headers=headers,
        json={**event_body(), "description": "Bring friends"},
    )
    assert response.status_code == 201
    event = response.json()
    path = f"/api/events/{event['id']}/publish"
    published = client.post(path, headers=headers)
    assert published.status_code == 200
    assert published.json()["status"] == "open"
    assert published.json()["discord_url"].endswith("/message")
    assert client.post(path, headers=headers).status_code == 409
    payload = client.app.state.discord.publish.call_args.args[0]
    assert "Bring friends" in payload["content"]
    assert "This is a lottery entry" not in payload["content"]
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
    assert client.get(path).json() == [
        {
            "name": "A",
            "players": [
                {
                    **players[0]["players"][0],
                    "weighting": 1.0,
                    "guaranteed_table": None,
                    "guaranteed_seat": False,
                }
            ],
        }
    ]
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
        "is_test": False,
        "guaranteed_seat": False,
        "real_name": "",
        "weighting": 1.0,
    }
    client.app.state.discord.bot.reset_mock()
    assert (
        client.get(path + "?signup_name=Mary%20from%20signups").json()["discord_name"]
        == "Mary from signups"
    )
    client.app.state.discord.bot.assert_not_called()
    assert client.put(path, json={"real_name": "Mary Smith"}).status_code == 403
    saved = client.put(path, headers=headers, json={"real_name": " Mary Smith "})
    assert saved.status_code == 200
    assert saved.json()["real_name"] == "Mary Smith"
    assert client.get(path + "?signup_name=Stale").json()["discord_name"] == "Mary"
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


def test_player_profiles_are_scoped_to_guild_and_global_weight_can_be_edited(client):
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
    created = client.put(
        "/api/players/123",
        headers=headers,
        json={"real_name": "Mary", "weighting": 5},
    )
    assert created.status_code == 200
    assert created.json()["weighting"] == 5
    updated = client.put(
        "/api/players/123",
        headers=headers,
        json={"real_name": "Mary", "weighting": 2.5},
    )
    assert updated.status_code == 200
    assert updated.json()["weighting"] == 2.5
    assert client.get("/api/players/123").json()["weighting"] == 2.5
    for invalid in (0, 10.1):
        assert (
            client.put(
                "/api/players/123",
                headers=headers,
                json={"real_name": "Mary", "weighting": invalid},
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
    assert saved.json()["weighting"] == 2.5
    with DBSession(client.app.state.engine) as db:
        assert db.get(PlayerProfile, ("other", "123")).real_name == "Private"
        assert db.get(PlayerProfile, ("other", "123")).weighting == 2.0


def test_admin_removes_organization_member_and_selection(client):
    owner = login(client)
    org_id = client.post(
        "/api/organizations", headers=owner, json={"name": "Friday Crew"}
    ).json()["id"]
    client.app.state.discord.identity.return_value = {
        "id": "second",
        "username": "Second",
    }
    second = login(client)
    client.app.state.discord.identity.return_value = {
        "id": "owner",
        "username": "organizer",
    }
    owner = login(client)
    assert (
        client.put(
            f"/api/organizations/{org_id}/members/second",
            headers=owner,
            json={"user_id": "second", "role": "editor"},
        ).status_code
        == 200
    )
    client.app.state.discord.identity.return_value = {
        "id": "second",
        "username": "Second",
    }
    second = login(client)
    client.put(
        "/api/organizations/selection",
        headers=second,
        json={"organization_id": org_id},
    )
    assert (
        client.delete(
            f"/api/organizations/{org_id}/members/owner", headers=second
        ).status_code
        == 403
    )
    client.app.state.discord.identity.return_value = {
        "id": "owner",
        "username": "organizer",
    }
    owner = login(client)
    assert (
        client.delete(
            f"/api/organizations/{org_id}/members/owner", headers=owner
        ).status_code
        == 403
    )
    assert (
        client.delete(
            f"/api/organizations/{org_id}/members/second", headers=owner
        ).status_code
        == 204
    )
    client.app.state.discord.identity.return_value = {
        "id": "second",
        "username": "Second",
    }
    login(client)
    assert client.get("/api/me").json()["organization"] is None


def test_settings_switch_channels_without_retargeting_existing_events(client):
    headers = login(client)
    base = client.app.state.discord
    scoped = {}

    def at(guild_id, channel_id):
        if (guild_id, channel_id) not in scoped:
            scoped[guild_id, channel_id] = Mock()
            scoped[
                guild_id, channel_id
            ].publish.return_value = base.publish.return_value
        return scoped[guild_id, channel_id]

    base.at.side_effect = at
    base.destination_channels.return_value = (
        "Server A",
        [{"id": "101", "name": "first"}, {"id": "102", "name": "second"}],
    )
    body = {"guild_id": "100", "channel_id": "101"}
    assert client.put("/api/settings", json=body).status_code == 403
    assert (
        client.put(
            "/api/settings",
            headers={**headers, "Origin": "https://evil.test"},
            json=body,
        ).status_code
        == 403
    )
    assert client.put("/api/settings", headers=headers, json=body).status_code == 200
    assert client.get("/api/me").json()["destination"] == "100:101"
    first = client.post("/api/events", headers=headers, json=event_body()).json()
    body["channel_id"] = "102"
    assert client.put("/api/settings", headers=headers, json=body).status_code == 200
    assert client.get("/api/events").json() == []
    path = f"/api/events/{first['id']}"
    assert client.get(path + "/signups").status_code == 404
    assert client.post(path + "/publish", headers=headers).status_code == 404
    assert client.put(path, headers=headers, json=event_body()).status_code == 409
    assert client.delete(path, headers=headers).status_code == 409
    body["channel_id"] = "101"
    client.put("/api/settings", headers=headers, json=body)
    published = client.post(path + "/publish", headers=headers)
    assert published.status_code == 200
    assert (
        published.json()["discord_url"]
        == "https://discord.com/channels/100/101/message"
    )
    scoped["100", "101"].publish.assert_called_once()
    assert ("100", "102") in scoped
    base.publish.assert_not_called()


def test_organization_discord_settings_follow_selection_and_admin_role(client):
    owner = login(client)
    discord = client.app.state.discord
    discord.destination_channels.return_value = (
        "Server A",
        [{"id": "101", "name": "personal"}, {"id": "102", "name": "shared"}],
    )
    discord.organization_channels.return_value = (
        "Server A",
        [{"id": "101", "name": "personal"}, {"id": "102", "name": "shared"}],
    )
    discord.bot.side_effect = lambda _method, path: {
        "name": "Server A" if path.startswith("/guilds/") else "personal"
    }
    assert (
        client.put(
            "/api/settings",
            headers=owner,
            json={"guild_id": "100", "channel_id": "101"},
        ).status_code
        == 200
    )
    org_id = client.post(
        "/api/organizations", headers=owner, json={"name": "Shared"}
    ).json()["id"]
    client.put(
        "/api/organizations/selection", headers=owner, json={"organization_id": org_id}
    )
    assert client.get("/api/settings").json()["organization_role"] == "admin"
    discord.destination_channels.side_effect = HTTPException(
        403, "You need Manage Server permission to configure this server."
    )
    assert (
        client.get("/api/settings/channels?guild_id=100").json()["channels"][1]["id"]
        == "102"
    )
    assert (
        client.put(
            "/api/settings",
            headers=owner,
            json={"guild_id": "100", "channel_id": "102"},
        ).status_code
        == 200
    )
    assert client.get("/api/settings").json()["selection"]["channel_id"] == "102"
    discord.organization_channels.assert_called()

    discord.identity.return_value = {"id": "second", "username": "Second"}
    second = login(client)
    discord.identity.return_value = {"id": "owner", "username": "organizer"}
    owner = login(client)
    client.put(
        f"/api/organizations/{org_id}/members/second",
        headers=owner,
        json={"user_id": "second", "role": "editor"},
    )
    discord.identity.return_value = {"id": "second", "username": "Second"}
    second = login(client)
    client.put(
        "/api/organizations/selection", headers=second, json={"organization_id": org_id}
    )
    assert client.get("/api/settings").json()["organization_role"] == "editor"
    assert client.get("/api/settings/channels?guild_id=100").status_code == 403
    assert client.get("/api/settings").json()["selection"]["channel_id"] == "102"
    assert (
        client.put(
            "/api/settings",
            headers=second,
            json={"guild_id": "100", "channel_id": "101"},
        ).status_code
        == 403
    )
    assert client.delete("/api/settings", headers=second).status_code == 409

    discord.identity.return_value = {"id": "owner", "username": "organizer"}
    owner = login(client)
    client.put(
        "/api/organizations/selection", headers=owner, json={"organization_id": None}
    )
    assert client.get("/api/settings").json()["selection"]["channel_id"] == "101"


def test_settings_are_per_user_and_recheck_permissions(client):
    first_headers = login(client)
    base = client.app.state.discord
    base.destination_channels.return_value = ("A", [{"id": "101", "name": "signups"}])
    client.put(
        "/api/settings",
        headers=first_headers,
        json={"guild_id": "100", "channel_id": "101"},
    )
    base.identity.return_value = {
        "id": "second",
        "username": "Second",
        "guilds": [{"id": "200", "name": "B", "owner": True}],
    }
    second_headers = login(client)
    base.destination_channels.return_value = ("B", [{"id": "201", "name": "other"}])
    client.put(
        "/api/settings",
        headers=second_headers,
        json={"guild_id": "200", "channel_id": "201"},
    )
    assert client.get("/api/settings").json()["selection"]["channel_id"] == "201"
    event = client.post("/api/events", headers=second_headers, json=event_body()).json()
    base.identity.return_value = {"id": "owner", "username": "organizer"}
    first_headers = login(client)
    assert client.get("/api/settings").json()["selection"]["channel_id"] == "101"
    assert client.get("/api/events").json() == []
    assert client.get(f"/api/events/{event['id']}/signups").status_code == 404
    base.at.return_value.authorize_destination.side_effect = HTTPException(
        403, "Permission removed"
    )
    assert client.get("/api/events").status_code == 403
    assert client.get("/api/settings").status_code == 200
    assert client.get("/api/me").status_code == 200
    assert client.post("/api/auth/logout", headers=first_headers).status_code == 204


def test_settings_reject_ineligible_channels_and_do_not_accept_credentials(client):
    headers = login(client)
    client.app.state.discord.destination_channels.return_value = (
        "A",
        [{"id": "101", "name": "signups"}],
    )
    assert (
        client.put(
            "/api/settings",
            headers=headers,
            json={"guild_id": "100", "channel_id": "999"},
        ).status_code
        == 403
    )
    assert (
        client.put(
            "/api/settings",
            headers=headers,
            json={"guild_id": "100", "channel_id": "101", "bot_token": "secret"},
        ).status_code
        == 422
    )
    client.app.state.discord.destination_channels.side_effect = HTTPException(
        403, "Not a manager"
    )
    assert (
        client.put(
            "/api/settings",
            headers=headers,
            json={"guild_id": "100", "channel_id": "101"},
        ).status_code
        == 403
    )


def test_login_requests_guild_scope_and_retains_only_manageable_servers(client):
    response = client.get("/api/auth/login", follow_redirects=False)
    assert parse_qs(urlparse(response.headers["location"]).query)["scope"] == [
        "identify guilds"
    ]
    client.app.state.discord.identity.return_value = {
        "id": "owner",
        "username": "Organizer",
        "guilds": [
            {"id": "100", "name": "Owner", "owner": True},
            {"id": "200", "name": "Manager", "permissions": "32"},
            {"id": "300", "name": "Member", "permissions": "1024"},
        ],
    }
    login(client)
    data = client.get("/api/settings").json()
    assert {g["id"] for g in data["guilds"]} == {"100", "200", "guild"}
    assert data["connect_url"] == "/api/auth/connect"
    assert "bot_token" not in data


def test_new_users_can_sign_in_to_setup_without_legacy_moderator_access(client):
    base = client.app.state.discord
    base.authorize.side_effect = HTTPException(403, "Not a moderator here")
    base.identity.return_value = {
        "id": "new-user",
        "username": "New",
        "guilds": [{"id": "100", "name": "Own server", "owner": True}],
    }
    headers = login(client)
    assert client.get("/api/me").json()["needs_setup"] is True
    setup = client.get("/api/settings").json()
    assert setup["selection"] is None
    assert setup["guilds"] == [{"id": "100", "name": "Own server"}]
    assert client.get("/api/events").status_code == 403
    base.destination_channels.return_value = (
        "Own server",
        [{"id": "101", "name": "games"}],
    )
    assert (
        client.put(
            "/api/settings",
            headers=headers,
            json={"guild_id": "100", "channel_id": "101"},
        ).status_code
        == 200
    )
    assert client.get("/api/me").json()["needs_setup"] is False
    assert client.get("/api/events").json() == []


def test_refresh_server_list_returns_to_settings_without_open_redirect(client):
    response = client.get("/api/auth/login?return_to=settings", follow_redirects=False)
    state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
    callback = client.get(
        f"/api/auth/callback?code=ok&state={state}", follow_redirects=False
    )
    assert callback.headers["location"].endswith("/#/settings")
    response = client.get(
        "/api/auth/login?return_to=https://evil.test", follow_redirects=False
    )
    state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
    callback = client.get(
        f"/api/auth/callback?code=ok&state={state}", follow_redirects=False
    )
    assert callback.headers["location"] == "http://localhost:5180"


def closing_event(client):
    headers = login(client)
    body = {
        **event_body(),
        "tables": [{"name": "A", "capacity": 1}, {"name": "B", "capacity": 1}],
    }
    base = client.app.state.discord
    base.publish.return_value["poll"]["answers"] = [
        {"answer_id": 9, "poll_media": {"text": "A · 1 seats"}},
        {"answer_id": 42, "poll_media": {"text": "B · 1 seats"}},
    ]
    event = client.post("/api/events", headers=headers, json=body).json()
    path = f"/api/events/{event['id']}"
    client.post(path + "/publish", headers=headers)
    users = {
        9: [
            {"id": "1", "username": "Mary"},
            {"id": "2", "username": "Dan"},
            {"id": "3", "username": "Shirley"},
        ],
        42: [{"id": "1", "username": "Mary"}, {"id": "4", "username": "Carl"}],
    }
    base.voter_users.side_effect = lambda message_id, answer_id: users[answer_id]
    return headers, event, path, users


def closing_message(finalized=True, future=False, counts=None):
    return {
        "poll": {
            "expiry": (
                datetime.now(UTC) + timedelta(hours=1)
                if future
                else datetime.now(UTC) - timedelta(seconds=1)
            ).isoformat(),
            "answers": [
                {"answer_id": 9, "poll_media": {"text": "A · 1 seats"}},
                {"answer_id": 42, "poll_media": {"text": "B · 1 seats"}},
            ],
            "results": {
                "is_finalized": finalized,
                "answer_counts": counts
                if counts is not None
                else [{"id": 9, "count": 3}, {"id": 42, "count": 2}],
            },
        }
    }


def test_event_player_settings_are_scoped_and_frozen_for_assignment(client):
    headers, event, path, _ = closing_event(client)
    discord = client.app.state.discord
    discord.table_signups.return_value = [
        {"name": "A", "players": [{"id": "1", "name": "Mary"}]},
        {"name": "B", "players": [{"id": "1", "name": "Mary"}]},
    ]
    discord.bot.return_value = {"username": "Mary"}
    assert (
        client.put(
            "/api/players/1", headers=headers, json={"real_name": ""}
        ).status_code
        == 200
    )
    setting = path + "/players/1/settings"
    assert client.put(setting, json={"guaranteed_table": "B"}).status_code == 403
    assert (
        client.put(setting, headers=headers, json={"guaranteed_table": "C"}).status_code
        == 422
    )
    assert (
        client.put(setting, headers=headers, json={"guaranteed_table": "B"}).status_code
        == 200
    )
    assert (
        client.put(setting, headers=headers, json={"weighting": 2.5}).status_code == 200
    )
    rows = client.get(path + "/signups").json()
    assert rows[0]["players"][0]["guaranteed_table"] == "B"
    assert rows[1]["players"][0]["weighting"] == 2.5
    assert client.get("/api/players/1").json()["weighting"] == 1.0
    assert client.get("/api/players/1").json()["guaranteed_seat"] is False
    discord.poll_message.return_value = closing_message()
    closed = client.post(path + "/close", headers=headers)
    assert closed.status_code == 200
    run = client.get(path + "/assignments").json()
    mary = next(p for p in run["snapshot"]["players"] if p["id"] == "1")
    assert mary["weight"] == 2.5
    assert mary["guaranteed_table"] == "B"
    assert run["result"]["assignments"]["1"] == "B"
    assert (
        client.put(setting, headers=headers, json={"weighting": 3}).status_code == 409
    )


def test_close_signups_assigns_once_and_replays_saved_results(client):
    from app.lottery import assign
    from app.models import LotteryRun

    headers, event, path, _ = closing_event(client)
    discord = client.app.state.discord
    discord.poll_message.side_effect = [closing_message(False, True), closing_message()]
    assert client.post(path + "/close").status_code == 403
    result = client.post(path + "/close", headers=headers)
    assert result.status_code == 200
    assert result.json()["status"] == "assigned"
    run = client.get(path + "/assignments").json()
    assert assign(run["snapshot"], run["seed"]) == run["result"]
    assert len(run["snapshot"]["players"]) == 4
    assert len(run["result"]["assignments"]) == 2
    assert len(run["result"]["waitlist"]) == 2
    assert client.get(path + "/signups").json() == run["result"]["tables"]
    assert client.post(path + "/close", headers=headers).json() == result.json()
    discord.end_poll.assert_called_once_with("message")
    assert discord.poll_message.call_count == 2
    discord.table_signups.assert_not_called()
    with DBSession(client.app.state.engine) as db:
        assert len(db.query(LotteryRun).all()) == 1
    assert client.delete(path, headers=headers).status_code == 409


def test_signup_exports_use_saved_placements_and_scope(client):
    import csv
    import io

    headers, event, path, _ = closing_event(client)
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    rows = client.get(path + "/signups").json()
    pdf = client.get(path + "/signups.pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF-")
    assert pdf.headers["content-disposition"].endswith('.pdf"')
    assert (
        client.get(path + "/signups.pdf?timezone=America%2FNew_York").status_code == 200
    )
    assert client.get(path + "/signups.pdf?timezone=Invalid").status_code == 400
    export = client.get(path + "/signups.csv")
    assert export.status_code == 200
    parsed = list(csv.DictReader(io.StringIO(export.content.decode("utf-8-sig"))))
    assert len(parsed) == sum(
        len(row["players"]) + len(row["waitlist"]) for row in rows
    )
    assert {row["Status"] for row in parsed} == {"Seated", "Waitlisted"}
    summary = client.get("/api/exports/signups.csv")
    all_rows = list(csv.DictReader(io.StringIO(summary.content.decode("utf-8-sig"))))
    assert len(all_rows) == len(parsed)
    assert {row["Event ID"] for row in all_rows} == {event["id"]}
    assert client.get("/api/events/missing/signups.csv").status_code == 404
    assert client.get("/api/events/missing/signups.pdf").status_code == 404


def test_assigned_exports_reflect_current_roster_and_display_names(client):
    import csv
    import io
    from unittest.mock import patch

    headers, _, path, _ = closing_event(client)
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    initial = client.get(path + "/signups").json()
    table = next(row for row in initial if row["waitlist"])
    removed = table["players"][0]["id"]
    promoted = table["waitlist"][0]["id"]
    assert (
        client.delete(path + f"/manager-players/{removed}", headers=headers).status_code
        == 200
    )
    current = client.get(path + "/signups").json()
    assert any(p["id"] == promoted for row in current for p in row["players"])
    assert all(p["id"] != removed for row in current for p in row["players"])
    assert (
        client.put(
            f"/api/players/{promoted}",
            headers=headers,
            json={"real_name": "Current display name"},
        ).status_code
        == 200
    )
    current = client.get(path + "/signups").json()
    csv_response = client.get(path + "/signups.csv")
    assert csv_response.headers["cache-control"] == "no-store"
    csv_rows = list(
        csv.DictReader(io.StringIO(csv_response.content.decode("utf-8-sig")))
    )
    assert any(
        row["Discord ID"] == promoted
        and row["Player"] == "Current display name"
        and row["Status"] == "Seated"
        for row in csv_rows
    )
    assert not any(
        row["Discord ID"] == removed and row["Status"] == "Seated" for row in csv_rows
    )
    with patch("app.main.event_pdf", return_value=b"%PDF-current") as render:
        pdf_response = client.get(path + "/signups.pdf")
    assert pdf_response.headers["cache-control"] == "no-store"
    assert render.call_args.args[1] == current
    assert client.get("/api/exports/signups.csv").headers["cache-control"] == "no-store"


def test_signup_csv_quotes_spreadsheet_formulas():
    import csv
    import io

    from app.signup_exports import event_csv

    content = event_csv(
        [
            {
                "name": "=TABLE()",
                "players": [{"id": "123", "name": "+discord", "display_name": "@Name"}],
                "waitlist": [],
            }
        ]
    )
    row = next(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
    assert row["Table"] == "'=TABLE()"
    assert row["Player"] == "'@Name"
    assert row["Discord username"] == "'+discord"


@pytest.mark.parametrize("table_count", [4, 6])
def test_pdf_fits_full_tables_on_one_portrait_page(table_count):
    import re
    from types import SimpleNamespace

    from app.signup_exports import event_pdf

    tables = [
        {"name": f"Table {index}", "capacity": 15} for index in range(table_count)
    ]
    rows = [
        {
            "name": table["name"],
            "players": [
                {
                    "name": f"player-{table_index}-{number}",
                    "display_name": f"Player {number}",
                }
                for number in range(15)
            ],
            "waitlist": [
                {"name": f"waiting-{table_index}-{number}"} for number in range(5)
            ],
        }
        for table_index, table in enumerate(tables)
    ]
    event = SimpleNamespace(
        title="Monday Tables",
        starts_at=1794265200,
        tables=tables,
        status="assigned",
    )
    pdf = event_pdf(event, rows)
    assert pdf.startswith(b"%PDF-")
    assert len(re.findall(rb"/Type\s*/Page\b", pdf)) == 1
    assert b"/MediaBox [ 0 0 612 792 ]" in pdf


def test_summary_export_respects_selected_organization(client):
    import csv
    import io

    headers, personal, path, _ = closing_event(client)
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    organization = client.post(
        "/api/organizations", headers=headers, json={"name": "Export Scope"}
    ).json()
    assert (
        client.put(
            "/api/organizations/selection",
            headers=headers,
            json={"organization_id": organization["id"]},
        ).status_code
        == 200
    )
    shared = client.post("/api/events", headers=headers, json=event_body()).json()
    response = client.get("/api/exports/signups.csv")
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert len(rows) == 1
    assert rows[0]["Event ID"] == shared["id"]
    assert rows[0]["Player"] == ""
    assert client.get(f"/api/events/{personal['id']}/signups.pdf").status_code == 404
    assert client.get(f"/api/events/{personal['id']}/signups.csv").status_code == 404


def test_manager_can_overfill_from_waitlist_without_auto_promotion_on_remove(client):
    from app.models import Announcement, EventWithdrawal

    headers, event, path, _ = closing_event(client)
    assert (
        client.put(
            "/api/settings/assignment",
            headers=headers,
            json={"automatic_weight_adjustment": True, "announce_table_changes": True},
        ).status_code
        == 200
    )
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    rows = client.get(path + "/signups").json()
    table = next(row for row in rows if row["waitlist"])
    seated = table["players"][0]["id"]
    waiting = table["waitlist"][0]["id"]
    target = f"{path}/assigned-players/{waiting}"
    assert client.post(target, json={"table": table["name"]}).status_code == 403
    assert (
        client.post(target, headers=headers, json={"table": "missing"}).status_code
        == 409
    )
    assert (
        client.post(target, headers=headers, json={"table": table["name"]}).status_code
        == 200
    )
    assert (
        client.post(target, headers=headers, json={"table": table["name"]}).status_code
        == 409
    )
    updated = next(
        row
        for row in client.get(path + "/signups").json()
        if row["name"] == table["name"]
    )
    assert len(updated["players"]) == 2
    assert len({player["id"] for player in updated["players"]}) == 2
    assert waiting not in {player["id"] for player in updated["waitlist"]}
    assert (
        client.get(path + "/assignments").json()["current_result"]["assignments"][
            waiting
        ]
        == table["name"]
    )
    assert (
        client.delete(f"{path}/manager-players/{seated}", headers=headers).status_code
        == 200
    )
    after = next(
        row
        for row in client.get(path + "/signups").json()
        if row["name"] == table["name"]
    )
    assert [player["id"] for player in after["players"]] == [waiting]
    assert [player["id"] for player in after["waitlist"]] == [
        player["id"] for player in updated["waitlist"]
    ]
    with DBSession(client.app.state.engine) as db:
        notice = (
            db.query(Announcement)
            .filter_by(event_id=event["id"], kind="promotion")
            .order_by(Announcement.part.desc())
            .first()
        )
        assert notice is not None
        assert (
            notice.payload["content"]
            == f"<@{seated}> has left their seat at **{table['name']}**."
        )
        assert notice.payload["allowed_mentions"] == {"parse": [], "users": [seated]}
        withdrawal = db.get(EventWithdrawal, (event["id"], seated))
        assert withdrawal is not None and withdrawal.promoted_id is None
        assert (
            db.query(Announcement)
            .filter_by(event_id=event["id"], kind="refresh")
            .count()
            == 1
        )


def test_manager_remove_from_full_table_promotes_next_waitlisted_player(client):
    from app.models import Announcement, EventWithdrawal

    headers, event, path, _ = closing_event(client)
    assert (
        client.put(
            "/api/settings/assignment",
            headers=headers,
            json={"automatic_weight_adjustment": True, "announce_table_changes": True},
        ).status_code
        == 200
    )
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    table = next(row for row in client.get(path + "/signups").json() if row["waitlist"])
    seated = table["players"][0]["id"]
    promoted = table["waitlist"][0]["id"]
    assert (
        client.delete(f"{path}/manager-players/{seated}", headers=headers).status_code
        == 200
    )
    after = next(
        row
        for row in client.get(path + "/signups").json()
        if row["name"] == table["name"]
    )
    assert [player["id"] for player in after["players"]] == [promoted]
    with DBSession(client.app.state.engine) as db:
        withdrawal = db.get(EventWithdrawal, (event["id"], seated))
        assert withdrawal is not None and withdrawal.promoted_id == promoted
        notice = (
            db.query(Announcement)
            .filter_by(event_id=event["id"], kind="promotion")
            .one()
        )
        expected = (
            f"<@{promoted}> has been promoted from the waitlist to **{table['name']}**."
        )
        assert notice.payload["content"] == expected


def test_reaction_promotion_notice_has_no_table_update_heading(client):
    from app.models import Announcement
    from app.withdrawals import withdraw

    headers, event, path, _ = closing_event(client)
    assert (
        client.put(
            "/api/settings/assignment",
            headers=headers,
            json={"automatic_weight_adjustment": True, "announce_table_changes": True},
        ).status_code
        == 200
    )
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    table = next(row for row in client.get(path + "/signups").json() if row["waitlist"])
    seated = table["players"][0]["id"]
    assert withdraw(client.app.state.engine, "guild", "channel", "announcement", seated)
    with DBSession(client.app.state.engine) as db:
        notice = (
            db.query(Announcement)
            .filter_by(event_id=event["id"], kind="promotion")
            .one()
        )
        assert "Table Update" not in notice.payload["content"]
        assert notice.payload["content"].startswith("<@")
        assert "has been promoted to" in notice.payload["content"]
        assert (
            db.query(Announcement)
            .filter_by(event_id=event["id"], kind="refresh")
            .count()
            == 1
        )


def test_table_change_notices_are_off_until_enabled(client):
    from app.models import Announcement

    headers, event, path, _ = closing_event(client)
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    table = next(row for row in client.get(path + "/signups").json() if row["waitlist"])
    seated = table["players"][0]["id"]
    assert (
        client.delete(f"{path}/manager-players/{seated}", headers=headers).status_code
        == 200
    )
    with DBSession(client.app.state.engine) as db:
        assert (
            db.query(Announcement)
            .filter_by(event_id=event["id"], kind="promotion")
            .count()
            == 0
        )
        assert (
            db.query(Announcement)
            .filter_by(event_id=event["id"], kind="refresh")
            .count()
            == 1
        )
    assert (
        client.put(
            "/api/settings/assignment",
            headers=headers,
            json={"automatic_weight_adjustment": True, "announce_table_changes": True},
        ).status_code
        == 200
    )
    target_table = next(
        row for row in client.get(path + "/signups").json() if row["waitlist"]
    )
    waiting = target_table["waitlist"][0]["id"]
    assert (
        client.post(
            f"{path}/assigned-players/{waiting}",
            headers=headers,
            json={"table": target_table["name"]},
        ).status_code
        == 200
    )
    with DBSession(client.app.state.engine) as db:
        notice = (
            db.query(Announcement)
            .filter_by(event_id=event["id"], kind="promotion")
            .one()
        )
        assert "has been promoted from the waitlist" in notice.payload["content"]
    assert (
        client.put(
            "/api/settings/assignment",
            headers=headers,
            json={"automatic_weight_adjustment": True, "announce_table_changes": False},
        ).status_code
        == 200
    )
    before = client.app.state.discord.send_announcement.call_count
    from app.announcements import deliver_event

    deliver_event(
        client.app.state.engine, client.app.state.discord, event["id"], limit=5
    )
    assert all(
        "has been promoted" not in call.args[1].get("content", "")
        for call in client.app.state.discord.send_announcement.call_args_list[before:]
    )
    with DBSession(client.app.state.engine) as db:
        saved = db.get(Announcement, notice.id)
        assert saved is not None and saved.deleted_at is not None


def test_assignment_settings_follow_selected_organization_and_admin_role(client):
    owner_headers = login(client)
    personal = {"automatic_weight_adjustment": False, "announce_table_changes": True}
    assert (
        client.put(
            "/api/settings/assignment", headers=owner_headers, json=personal
        ).json()
        == personal
    )
    org = client.post(
        "/api/organizations", headers=owner_headers, json={"name": "Settings Scope"}
    ).json()
    assert (
        client.put(
            "/api/organizations/selection",
            headers=owner_headers,
            json={"organization_id": org["id"]},
        ).status_code
        == 200
    )
    defaults = {"automatic_weight_adjustment": True, "announce_table_changes": False}
    assert client.get("/api/settings/assignment").json() == defaults
    shared = {"automatic_weight_adjustment": False, "announce_table_changes": False}
    assert (
        client.put(
            "/api/settings/assignment", headers=owner_headers, json=shared
        ).json()
        == shared
    )
    client.app.state.discord.identity.return_value = {
        "id": "editor",
        "username": "Editor",
    }
    editor_headers = login(client)
    client.app.state.discord.identity.return_value = {
        "id": "owner",
        "username": "organizer",
    }
    owner_headers = login(client)
    assert (
        client.put(
            f"/api/organizations/{org['id']}/members/editor",
            headers=owner_headers,
            json={"user_id": "editor", "role": "editor"},
        ).status_code
        == 200
    )
    client.app.state.discord.identity.return_value = {
        "id": "editor",
        "username": "Editor",
    }
    editor_headers = login(client)
    assert (
        client.put(
            "/api/organizations/selection",
            headers=editor_headers,
            json={"organization_id": org["id"]},
        ).status_code
        == 200
    )
    assert client.get("/api/settings/assignment").json() == shared
    assert (
        client.put(
            "/api/settings/assignment", headers=editor_headers, json=personal
        ).status_code
        == 403
    )
    client.app.state.discord.identity.return_value = {
        "id": "owner",
        "username": "organizer",
    }
    owner_headers = login(client)
    assert (
        client.put(
            "/api/organizations/selection",
            headers=owner_headers,
            json={"organization_id": None},
        ).status_code
        == 200
    )
    assert client.get("/api/settings/assignment").json() == personal


def test_close_waits_for_finalization_and_freezes_weights_before_retries(client):
    from app.models import Event, LotteryRun, PlayerProfile

    headers, event, path, _ = closing_event(client)
    with DBSession(client.app.state.engine) as db:
        db.add(
            PlayerProfile(
                guild_id="guild",
                discord_id="2",
                discord_name="Dan",
                real_name="",
                weighting=2.0,
            )
        )
        db.commit()
    discord = client.app.state.discord
    discord.poll_message.side_effect = [
        closing_message(False, True),
        closing_message(False),
        closing_message(False),
        closing_message(),
    ]
    pending = client.post(path + "/close", headers=headers)
    assert pending.status_code == 202
    assert pending.json()["status"] == "closing"
    with DBSession(client.app.state.engine) as db:
        assert db.get(LotteryRun, event["id"]) is None
        seed = db.get(Event, event["id"]).close_seed
        db.get(PlayerProfile, ("guild", "2")).weighting = 9.0
        db.commit()
    assert client.post(path + "/close", headers=headers).status_code == 200
    run = client.get(path + "/assignments").json()
    assert run["seed"] == seed
    assert (
        next(p for p in run["snapshot"]["players"] if p["id"] == "2")["weight"] == 2.0
    )
    discord.end_poll.assert_called_once()


def test_incomplete_voters_do_not_create_partial_assignments(client):
    from app.models import LotteryRun

    headers, event, path, users = closing_event(client)
    discord = client.app.state.discord
    discord.poll_message.return_value = closing_message()
    missing = users[9].pop()
    assert client.post(path + "/close", headers=headers).status_code == 202
    with DBSession(client.app.state.engine) as db:
        assert db.get(LotteryRun, event["id"]) is None
    users[9].append(missing)
    assert client.post(path + "/close", headers=headers).status_code == 200
    discord.end_poll.assert_not_called()


def test_close_retries_after_discord_failure_without_redraw(client):
    from app.models import Event, LotteryRun

    headers, event, path, users = closing_event(client)
    discord = client.app.state.discord
    discord.poll_message.return_value = closing_message()
    discord.voter_users.side_effect = HTTPException(502, "Discord unavailable")
    assert client.post(path + "/close", headers=headers).status_code == 502
    with DBSession(client.app.state.engine) as db:
        assert db.get(LotteryRun, event["id"]) is None
        saved = db.get(Event, event["id"])
        seed = saved.close_seed
        assert saved.close_token is None
        assert saved.status == "closing"
    discord.voter_users.side_effect = lambda msg, answer: users[answer]
    assert client.post(path + "/close", headers=headers).status_code == 200
    assert client.get(path + "/assignments").json()["seed"] == seed


def test_concurrent_close_only_one_worker_claims_the_event(client):
    from threading import Event as Gate

    headers, event, path, _ = closing_event(client)
    entered, release = Gate(), Gate()
    discord = client.app.state.discord
    discord.poll_message.side_effect = [closing_message(False, True), closing_message()]

    def block(message_id):
        entered.set()
        assert release.wait(5)

    discord.end_poll.side_effect = block
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(client.post, path + "/close", headers=headers)
        try:
            assert entered.wait(5)
            assert client.post(path + "/close", headers=headers).status_code == 409
        finally:
            release.set()
        assert first.result(timeout=5).status_code == 200
    discord.end_poll.assert_called_once()


def test_expired_close_claim_can_be_recovered(client):
    from app.closing import LEASE_SECONDS
    from app.models import Event

    headers, event, path, _ = closing_event(client)
    with DBSession(client.app.state.engine) as db:
        saved = db.get(Event, event["id"])
        saved.status = "closing"
        saved.close_token = "interrupted"
        saved.close_started_at = time.time() - LEASE_SECONDS - 1
        saved.close_seed = "original-seed"
        saved.close_weights = {}
        db.commit()
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    assert client.get(path + "/assignments").json()["seed"] == "original-seed"


def test_close_validates_poll_identity_and_supports_zero_votes(client):
    from app.models import LotteryRun

    headers, event, path, _ = closing_event(client)
    discord = client.app.state.discord
    message = closing_message()
    message["poll"]["answers"][0]["answer_id"] = 123
    discord.poll_message.return_value = message
    assert client.post(path + "/close", headers=headers).status_code == 502
    with DBSession(client.app.state.engine) as db:
        assert db.get(LotteryRun, event["id"]) is None
    discord.poll_message.return_value = closing_message(counts=[])
    discord.voter_users.side_effect = lambda msg, answer: []
    assert client.post(path + "/close", headers=headers).status_code == 200
    assert client.get(path + "/assignments").json()["result"]["assignments"] == {}


def test_close_and_results_are_scoped_to_destination(client):
    from app.models import Event

    headers, event, path, _ = closing_event(client)
    assert client.get(path + "/assignments").status_code == 409
    with DBSession(client.app.state.engine) as db:
        db.get(Event, event["id"]).guild_id = "different"
        db.commit()
    assert client.post(path + "/close", headers=headers).status_code == 404
    assert client.get(path + "/assignments").status_code == 404
    client.app.state.discord.end_poll.assert_not_called()


def test_close_immediately_announces_assignments_without_duplicate_delivery(client):
    from app.announcements import dispatch_due
    from app.models import Announcement

    headers, event, path, _ = closing_event(client)
    discord = client.app.state.discord
    discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    delivery = client.get(path + "/announcement").json()
    assert delivery["status"] == "pending"
    assert delivery["url"].endswith("/channel/announcement")
    channel, payload = discord.send_announcement.call_args_list[0].args
    assert channel == "channel"
    assert "Table Assignments" in payload["content"]
    assert payload["enforce_nonce"] is True
    assert payload["allowed_mentions"]["parse"] == []
    assert client.post(path + "/close", headers=headers).status_code == 200
    dispatch_due(client.app.state.engine, lambda guild, channel: discord)
    assert client.get(path + "/announcement").json()["status"] == "sent"
    assert discord.send_announcement.call_count == 2
    with DBSession(client.app.state.engine) as db:
        assert db.query(Announcement).filter_by(event_id=event["id"]).count() == 2


def test_assignment_changes_refresh_existing_discord_message_with_retry(client):
    from app.announcements import dispatch_due
    from app.discord_api import DiscordRequestError
    from app.models import Announcement

    headers, event, path, _ = closing_event(client)
    discord = client.app.state.discord
    discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    table = next(row for row in client.get(path + "/signups").json() if row["waitlist"])
    waiting = table["waitlist"][0]["id"]
    assert (
        client.post(
            f"{path}/assigned-players/{waiting}",
            headers=headers,
            json={"table": table["name"]},
        ).status_code
        == 200
    )
    with DBSession(client.app.state.engine) as db:
        refresh = (
            db.query(Announcement).filter_by(event_id=event["id"], kind="refresh").one()
        )
        assert refresh.state == "pending"
    assert client.get(path + "/announcement").json()["update_pending"] is True
    discord.at.return_value.edit_announcement.side_effect = DiscordRequestError(429)
    dispatch_due(client.app.state.engine, lambda guild, channel: discord)
    with DBSession(client.app.state.engine) as db:
        refresh = (
            db.query(Announcement).filter_by(event_id=event["id"], kind="refresh").one()
        )
        assert refresh.state == "pending"
        refresh.next_attempt = 0
        db.commit()
    discord.at.return_value.edit_announcement.side_effect = None
    sent_before = discord.send_announcement.call_count
    dispatch_due(client.app.state.engine, lambda guild, channel: discord)
    assert discord.send_announcement.call_count == sent_before
    channel, message_id, edit = discord.at.return_value.edit_announcement.call_args.args
    assert (channel, message_id) == ("channel", "announcement")
    assert edit["allowed_mentions"] == {"parse": [], "users": []}
    assert "<@" not in edit["content"]
    table_field = next(
        field
        for field in edit["embeds"][0]["fields"]
        if field["name"].startswith(table["name"])
    )
    assert table_field["name"].endswith("(2/1)")
    assert f"<@{waiting}>" in table_field["value"]
    with DBSession(client.app.state.engine) as db:
        row = (
            db.query(Announcement)
            .filter_by(event_id=event["id"], kind="assignment")
            .one()
        )
        assert row.payload["embeds"] == edit["embeds"]
        refresh = (
            db.query(Announcement).filter_by(event_id=event["id"], kind="refresh").one()
        )
        assert refresh.state == "sent" and refresh.deleted_at is not None
        db.add(
            Announcement(
                id="extra-assignment-part",
                event_id=event["id"],
                part=3,
                kind="assignment",
                channel_id="channel",
                payload={"content": "Old extra roster", "nonce": "extra"},
                state="sent",
                message_id="old-extra",
                created_at=time.time(),
                next_attempt=time.time(),
            )
        )
        db.commit()
    assert (
        client.delete(f"{path}/manager-players/{waiting}", headers=headers).status_code
        == 200
    )
    dispatch_due(client.app.state.engine, lambda guild, channel: discord)
    _, extra_id, extra_edit = discord.at.return_value.edit_announcement.call_args.args
    assert extra_id == "old-extra"
    assert extra_edit["embeds"] == []
    assert extra_edit["content"].startswith("Assignments updated above")
    assert client.get(path + "/announcement").json()["update_pending"] is False


def test_announcement_failure_retries_without_redrawing(client):
    from app.announcements import dispatch_due
    from app.discord_api import DiscordRequestError
    from app.models import Announcement

    headers, event, path, _ = closing_event(client)
    discord = client.app.state.discord
    discord.poll_message.return_value = closing_message()
    discord.send_announcement.side_effect = DiscordRequestError(429)
    assert client.post(path + "/close", headers=headers).status_code == 200
    original = client.get(path + "/assignments").json()
    assert client.get(path + "/announcement").json()["status"] == "pending"
    discord.send_announcement.side_effect = None
    with DBSession(client.app.state.engine) as db:
        db.query(Announcement).filter_by(event_id=event["id"]).update(
            {"next_attempt": 0}
        )
        db.commit()
    dispatch_due(client.app.state.engine, lambda guild, channel: discord)
    assert client.get(path + "/announcement").json()["status"] == "sent"
    assert client.get(path + "/assignments").json() == original
    assert discord.send_announcement.call_count == 3
    discord.end_poll.assert_not_called()


def test_ambiguous_announcement_is_reconciled_without_blind_repost(client):
    from app.announcements import dispatch_due
    from app.discord_api import DiscordRequestError
    from app.models import Announcement

    headers, event, path, _ = closing_event(client)
    discord = client.app.state.discord
    discord.poll_message.return_value = closing_message()
    discord.send_announcement.side_effect = DiscordRequestError(None)
    client.post(path + "/close", headers=headers)
    discord.send_announcement.side_effect = None
    discord.find_announcement.return_value = "accepted-but-response-lost"
    with DBSession(client.app.state.engine) as db:
        db.query(Announcement).filter_by(event_id=event["id"]).update(
            {"next_attempt": 0}
        )
        db.commit()
    dispatch_due(client.app.state.engine, lambda guild, channel: discord)
    assert client.get(path + "/announcement").json()["status"] == "sent"
    assert discord.send_announcement.call_count == 2
    discord.find_announcement.assert_called_once()


def test_unconfirmed_delivery_requires_explicit_repost_confirmation(client):
    from app.announcements import dispatch_due
    from app.discord_api import DiscordRequestError
    from app.models import Announcement

    headers, event, path, _ = closing_event(client)
    discord = client.app.state.discord
    discord.poll_message.return_value = closing_message()
    discord.send_announcement.side_effect = DiscordRequestError(None)
    client.post(path + "/close", headers=headers)
    original = client.get(path + "/assignments").json()
    discord.find_announcement.return_value = None
    with DBSession(client.app.state.engine) as db:
        db.query(Announcement).filter_by(event_id=event["id"]).update(
            {"next_attempt": 0}
        )
        db.commit()
    dispatch_due(client.app.state.engine, lambda guild, channel: discord)
    assert client.get(path + "/announcement").json()["status"] == "needs_review"
    assert (
        client.post(path + "/announcement/retry", headers=headers, json={}).status_code
        == 409
    )
    discord.send_announcement.side_effect = None
    assert (
        client.post(
            path + "/announcement/retry", json={"confirm_repost": True}
        ).status_code
        == 403
    )
    retried = client.post(
        path + "/announcement/retry", headers=headers, json={"confirm_repost": True}
    )
    assert retried.json()["status"] == "pending"
    dispatch_due(client.app.state.engine, lambda guild, channel: discord)
    assert client.get(path + "/announcement").json()["status"] == "sent"
    assert client.get(path + "/assignments").json() == original


def test_persisted_test_users_run_through_publish_close_and_announce(client):
    from app.models import Announcement, Event, LotteryRun, PlayerProfile

    headers = login(client)
    assert client.get("/api/me").json()["can_populate_test_users"] is True
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    path = f"/api/events/{event['id']}"
    assert client.post(path + "/test-users", json={"players": 30}).status_code == 403
    populated = client.post(path + "/test-users", headers=headers, json={"players": 30})
    assert populated.status_code == 200
    assert populated.json()["status"] == "draft"
    assert populated.json()["is_test"] is True
    signups = client.get(path + "/signups").json()
    assert len(signups[0]["players"]) == 30
    pid = signups[0]["players"][0]["id"]
    profile = client.get(f"/api/players/{pid}")
    assert profile.status_code == 200
    assert profile.json()["discord_name"] == "Test Player 001"
    assert profile.json()["is_test"] is True
    assert (
        client.put(
            f"/api/players/{pid}",
            headers=headers,
            json={"real_name": "Editable test name", "weighting": 3.5},
        ).status_code
        == 200
    )
    named = client.get(path + "/signups").json()[0]["players"][0]
    assert named["display_name"] == "Editable test name"
    assert named["name"] == "Test Player 001"
    with DBSession(client.app.state.engine) as db:
        assert db.get(Event, event["id"]).close_seed is None
        assert db.get(LotteryRun, event["id"]) is None
        assert db.query(Announcement).count() == 0
        weight = db.get(PlayerProfile, ("guild", pid)).weighting
        assert weight == 3.5
    discord = client.app.state.discord
    discord.send_announcement.assert_not_called()
    assert client.post(path + "/publish", headers=headers).status_code == 200
    assert "[TEST]" in discord.publish.call_args.args[0]["content"]
    discord.table_signups.return_value = [
        {"name": "Clocktower", "players": [{"id": "999", "name": "Real Signup"}]}
    ]
    assert len(client.get(path + "/signups").json()[0]["players"]) == 31
    final_poll = {
        "poll": {
            "expiry": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
            "answers": [
                {"answer_id": 9, "poll_media": {"text": "Clocktower · 15 seats"}}
            ],
            "results": {"is_finalized": True, "answer_counts": [{"id": 9, "count": 1}]},
        }
    }
    open_poll = {
        "poll": {
            **final_poll["poll"],
            "expiry": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "results": {"is_finalized": False},
        }
    }
    discord.poll_message.side_effect = [open_poll, final_poll]
    discord.voter_users.return_value = [{"id": "999", "username": "Real Signup"}]
    assert client.post(path + "/close", headers=headers).status_code == 200
    discord.end_poll.assert_called_once_with("message")
    run = client.get(path + "/assignments").json()
    assert len(run["snapshot"]["players"]) == 31
    assert run["snapshot"]["is_test"] is True
    assert (
        next(p for p in run["snapshot"]["players"] if p["id"] == pid)["weight"]
        == weight
    )
    assert len(run["result"]["assignments"]) == 15
    assert len(run["result"]["waitlist"]) == 16
    assert (
        client.post(
            path + "/test-users", headers=headers, json={"players": 2}
        ).status_code
        == 409
    )
    rows = client.get(path + "/signups").json()
    displayed = [p for row in rows for key in ("players", "waitlist") for p in row[key]]
    assert (
        next(p for p in displayed if p["id"] == pid)["display_name"]
        == "Editable test name"
    )
    client.put(
        f"/api/players/{pid}", headers=headers, json={"real_name": "Updated Display"}
    )
    rows = client.get(path + "/signups").json()
    assert any(
        p.get("display_name") == "Updated Display"
        for row in rows
        for key in ("players", "waitlist")
        for p in row[key]
    )
    assert client.get(path + "/assignments").json() == run
    assert "[TEST]" in discord.send_announcement.call_args_list[0].args[1]["content"]
    for call in discord.send_announcement.call_args_list:
        payload = call.args[1]
        assert "Editable test name" not in payload["content"]
        assert "Updated Display" not in payload["content"]
        assert "<@test-" not in payload["content"]
        assert payload["allowed_mentions"].get("users", []) == []


def test_reaction_close_merges_test_players_with_manager_overrides(client):
    from app.models import Event, LotteryRun

    headers = login(client)
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    path = f"/api/events/{event['id']}"
    assert (
        client.post(
            path + "/test-users", headers=headers, json={"players": 3}
        ).status_code
        == 200
    )
    users = client.get(path + "/signups").json()[0]["players"]
    assert (
        client.put(
            f"{path}/manager-players/{users[0]['id']}",
            headers=headers,
            json={"table": "Clocktower", "name": "Updated Test Player"},
        ).status_code
        == 200
    )
    assert (
        client.delete(
            f"{path}/manager-players/{users[1]['id']}", headers=headers
        ).status_code
        == 200
    )
    with DBSession(client.app.state.engine) as db:
        saved = db.get(Event, event["id"])
        saved.status = "open"
        saved.signup_mode = "reactions"
        saved.message_id = "message"
        saved.reaction_checkpoint = time.time()
        saved.closes_at = time.time() + 60
        db.commit()
    response = client.post(path + "/close", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "assigned"
    with DBSession(client.app.state.engine) as db:
        run = db.get(LotteryRun, event["id"])
        assert run is not None
        players = run.snapshot["players"]
        assert len(players) == 2
        assert len({player["id"] for player in players}) == 2
        assert (
            next(player for player in players if player["id"] == users[0]["id"])["name"]
            == "Updated Test Player"
        )


def test_test_population_requires_server_allowlist_and_can_be_cleared(client):
    headers = login(client)
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    path = f"/api/events/{event['id']}/test-users"
    assert client.post(path, headers=headers, json={"players": 1001}).status_code == 422
    client.post(path, headers=headers, json={"players": 5})
    assert (
        len(client.get(f"/api/events/{event['id']}/signups").json()[0]["players"]) == 5
    )
    assert (
        client.post(path, headers=headers, json={"players": 0}).json()["is_test"]
        is False
    )
    assert client.get(f"/api/events/{event['id']}/signups").json()[0]["players"] == []
    client.app.state.discord.identity.return_value = {
        "id": "other",
        "username": "Other",
    }
    headers = login(client)
    assert client.get("/api/me").json()["can_populate_test_users"] is False
    assert client.post(path, headers=headers, json={"players": 5}).status_code == 403


def test_test_population_and_announcements_are_destination_scoped(client):
    from app.models import Event

    headers, event, path, _ = closing_event(client)
    with DBSession(client.app.state.engine) as db:
        db.get(Event, event["id"]).guild_id = "other"
        db.commit()
    assert (
        client.post(
            path + "/test-users", headers=headers, json={"players": 30}
        ).status_code
        == 404
    )
    assert client.get(path + "/announcement").status_code == 404
    assert (
        client.post(
            path + "/announcement/retry", headers=headers, json={"confirm_repost": True}
        ).status_code
        == 404
    )


def test_test_profiles_reused_after_clear_and_event_deletion(client):
    headers = login(client)
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    path = f"/api/events/{event['id']}"
    client.post(path + "/test-users", headers=headers, json={"players": 2})
    players = client.get(path + "/signups").json()[0]["players"]
    pid = players[0]["id"]
    profile_path = f"/api/players/{pid}"
    for weight in (0, -1, 10.1, "nan", "inf"):
        assert (
            client.put(
                profile_path,
                headers=headers,
                json={"real_name": "Test", "weighting": weight},
            ).status_code
            == 422
        )
    assert (
        client.put(profile_path, json={"real_name": "Test", "weighting": 2}).status_code
        == 403
    )
    saved = client.put(
        profile_path,
        headers=headers,
        json={"real_name": "Saved Name", "weighting": 0.25},
    ).json()
    assert saved["is_test"] is True
    client.post(path + "/test-users", headers=headers, json={"players": 0})
    assert client.get(profile_path).json() == saved
    assert client.delete(path, headers=headers).status_code == 204
    assert client.get(profile_path).json() == saved
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    path = f"/api/events/{event['id']}"
    client.post(path + "/test-users", headers=headers, json={"players": 3})
    reused = client.get(path + "/signups").json()[0]["players"]
    assert {p["id"] for p in players}.issubset({p["id"] for p in reused})
    assert len({p["id"] for p in reused}) == 3
    assert client.get(profile_path).json() == saved
    from app.models import PlayerProfile

    with DBSession(client.app.state.engine) as db:
        db.get(PlayerProfile, ("guild", pid)).guild_id = "elsewhere"
        db.commit()
    assert client.get(profile_path).status_code == 404
    assert (
        client.put(
            profile_path, headers=headers, json={"real_name": "No", "weighting": 1}
        ).status_code
        == 404
    )


def test_guarantee_conflict_does_not_end_poll_and_can_be_corrected(client):
    from app.models import Event, LotteryRun

    headers = login(client)
    body = event_body()
    body["tables"][0]["capacity"] = 1
    event = client.post("/api/events", headers=headers, json=body).json()
    path = f"/api/events/{event['id']}"
    client.post(path + "/test-users", headers=headers, json={"players": 2})
    players = client.get(path + "/signups").json()[0]["players"]
    for player in players:
        result = client.put(
            f"/api/players/{player['id']}",
            headers=headers,
            json={
                "real_name": "Volunteer",
                "guaranteed_seat": True,
            },
        )
        assert result.status_code == 200
        assert result.json()["guaranteed_seat"] is True
    client.post(path + "/publish", headers=headers)
    discord = client.app.state.discord
    discord.table_signups.return_value = [{"name": "Clocktower", "players": []}]
    conflict = client.post(path + "/close", headers=headers)
    assert conflict.status_code == 409
    assert "exceed capacity" in conflict.json()["detail"]
    discord.end_poll.assert_not_called()
    discord.send_announcement.assert_not_called()
    with DBSession(client.app.state.engine) as db:
        assert db.get(Event, event["id"]).status == "open"
        assert db.get(LotteryRun, event["id"]) is None
    client.put(
        f"/api/players/{players[1]['id']}",
        headers=headers,
        json={"real_name": "Player", "guaranteed_seat": False},
    )
    discord.poll_message.return_value = {
        "poll": {
            "expiry": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
            "answers": [
                {"answer_id": 9, "poll_media": {"text": "Clocktower · 1 seats"}}
            ],
            "results": {"is_finalized": True, "answer_counts": []},
        }
    }
    discord.voter_users.return_value = []
    assert client.post(path + "/close", headers=headers).status_code == 200
    run = client.get(path + "/assignments").json()
    assert run["result"]["assignments"] == {players[0]["id"]: "Clocktower"}
    assert (
        next(p for p in run["snapshot"]["players"] if p["id"] == players[0]["id"])[
            "guaranteed_seat"
        ]
        is True
    )
    client.put(
        f"/api/players/{players[0]['id']}",
        headers=headers,
        json={"real_name": "Changed", "guaranteed_seat": False},
    )
    assert client.get(path + "/assignments").json() == run


def test_display_names_are_guild_scoped_and_clear_to_discord_name(client):
    from app.models import PlayerProfile

    headers = login(client)
    client.app.state.discord.bot.return_value = {"username": "MaryDiscord"}
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    path = f"/api/events/{event['id']}"
    client.post(path + "/publish", headers=headers)
    client.app.state.discord.table_signups.return_value = [
        {"name": "Clocktower", "players": [{"id": "123", "name": "MaryDiscord"}]}
    ]
    with DBSession(client.app.state.engine) as db:
        db.add(
            PlayerProfile(
                guild_id="other",
                discord_id="123",
                discord_name="OtherDiscord",
                real_name="Private Display",
            )
        )
        db.commit()
    assert "display_name" not in client.get(path + "/signups").json()[0]["players"][0]
    client.put(
        "/api/players/123", headers=headers, json={"real_name": " Mary Display "}
    )
    player = client.get(path + "/signups").json()[0]["players"][0]
    assert player == {
        "id": "123",
        "name": "MaryDiscord",
        "display_name": "Mary Display",
        "weighting": 1.0,
        "guaranteed_table": None,
        "guaranteed_seat": False,
    }
    client.put("/api/players/123", headers=headers, json={"real_name": "   "})
    assert client.get(path + "/signups").json()[0]["players"][0] == {
        "id": "123",
        "name": "MaryDiscord",
        "weighting": 1.0,
        "guaranteed_table": None,
        "guaranteed_seat": False,
    }


def test_archive_preserves_assignments_and_discord_and_is_idempotent(client):
    headers, event, path, _ = closing_event(client)
    assert client.post(path + "/archive", headers=headers).status_code == 409
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    run = client.get(path + "/assignments").json()
    signups = client.get(path + "/signups").json()
    calls = list(client.app.state.discord.mock_calls)
    assert client.post(path + "/archive").status_code == 403
    archived = client.post(path + "/archive", headers=headers)
    assert archived.status_code == 200
    assert archived.json()["archived_at"] > 0
    assert archived.json()["status"] == "assigned"
    assert client.post(path + "/archive", headers=headers).json() == archived.json()
    assert client.get(path + "/assignments").json() == run
    assert client.get(path + "/signups").json() == signups
    assert any(
        row["id"] == event["id"] and row["archived_at"]
        for row in client.get("/api/events").json()
    )
    # Authorization may contact Discord; archiving must not publish or delete anything.
    assert sum(
        c[0] == "send_announcement" for c in client.app.state.discord.mock_calls
    ) == sum(c[0] == "send_announcement" for c in calls)
    client.app.state.discord.delete_poll.assert_not_called()
    from app.models import Event

    with DBSession(client.app.state.engine) as db:
        db.get(Event, event["id"]).channel_id = "another-channel"
        db.commit()
    assert client.post(path + "/archive", headers=headers).status_code == 404


def test_close_can_delete_signup_message_and_archive_can_delete_announcements(client):
    from app.announcements import dispatch_due

    headers, event, path, _ = closing_event(client)
    client.app.state.discord.poll_message.return_value = closing_message()
    closed = client.post(path + "/close?delete_signup_message=true", headers=headers)
    assert closed.status_code == 200
    assert closed.json()["discord_url"] is None
    assert closed.json()["signup_deleted_at"] > 0
    scoped = client.app.state.discord.at.return_value
    scoped.delete_poll.assert_called_once_with("message")
    dispatch_due(
        client.app.state.engine, lambda guild, channel: client.app.state.discord
    )
    archived = client.post(
        path + "/archive?delete_discord_messages=true", headers=headers
    )
    assert archived.status_code == 200
    assert archived.json()["archived_at"] > 0
    assert scoped.delete_poll.call_count == 3
    while True:
        cleanup = client.post(path + "/discord-messages/delete", headers=headers)
        assert cleanup.status_code == 200
        if cleanup.json()["discord_cleanup_remaining"] == 0:
            break
    assert client.get(path + "/announcement").json()["status"] == "deleted"
    assert (
        client.post(
            path + "/announcement/retry", headers=headers, json={"confirm_repost": True}
        ).status_code
        == 409
    )
    assert (
        client.post(
            path + "/archive?delete_discord_messages=true", headers=headers
        ).status_code
        == 200
    )
    assert scoped.delete_poll.call_count == 3


def test_failed_archive_discord_cleanup_can_be_retried(client):
    from app.announcements import dispatch_due
    from app.discord_api import DiscordRequestError

    headers, event, path, _ = closing_event(client)
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    dispatch_due(
        client.app.state.engine, lambda guild, channel: client.app.state.discord
    )
    scoped = client.app.state.discord.at.return_value
    scoped.delete_poll.side_effect = [
        None,
        DiscordRequestError(403),
        None,
        None,
        None,
        None,
        None,
    ]
    failed = client.post(
        path + "/archive?delete_discord_messages=true", headers=headers
    )
    assert failed.status_code == 200
    assert failed.json()["archived_at"] is not None
    assert failed.json()["discord_cleanup_remaining"] == 2
    assert "403" in failed.json()["discord_cleanup_error"]
    retried = client.post(path + "/discord-messages/delete", headers=headers)
    assert retried.status_code == 200
    assert retried.json()["discord_cleanup_remaining"] == 0
    retried = client.post(path + "/discord-messages/delete", headers=headers)
    assert retried.status_code == 200
    assert retried.json()["discord_cleanup_remaining"] == 0
    assert retried.json()["discord_cleanup_error"] is None
    assert scoped.delete_poll.call_count == 4
    assert (
        next(
            row for row in client.get("/api/events").json() if row["id"] == event["id"]
        )["discord_url"]
        is None
    )


def test_archive_cleanup_respects_rate_limit_and_resumes_after_plain_archive(client):
    from app.announcements import dispatch_due
    from app.discord_api import DiscordRequestError
    from app.models import Announcement

    headers, event, path, _ = closing_event(client)
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    dispatch_due(
        client.app.state.engine, lambda guild, channel: client.app.state.discord
    )
    with DBSession(client.app.state.engine) as db:
        for part in range(4, 14):
            db.add(
                Announcement(
                    id=f"extra-{part}",
                    event_id=event["id"],
                    part=part,
                    channel_id="channel",
                    payload={},
                    state="sent",
                    message_id=f"extra-{part}",
                    created_at=0,
                    next_attempt=0,
                )
            )
        db.commit()
    scoped = client.app.state.discord.at.return_value
    scoped.delete_poll.side_effect = [None, DiscordRequestError(429, 0.25)]
    first = client.post(path + "/archive?delete_discord_messages=true", headers=headers)
    assert first.status_code == 200
    assert first.json()["archived_at"] is not None
    assert first.json()["discord_cleanup_remaining"] == 12
    assert first.json()["discord_cleanup_retry_after"] == 0.25
    scoped.delete_poll.side_effect = None
    while True:
        result = client.post(path + "/discord-messages/delete", headers=headers)
        assert result.status_code == 200
        if result.json()["discord_cleanup_remaining"] == 0:
            break
    assert scoped.delete_poll.call_count == 14
    assert result.json()["discord_url"] is None
    assert (
        client.post(path + "/discord-messages/delete", headers=headers).json()[
            "discord_cleanup_remaining"
        ]
        == 0
    )


def test_discord_cleanup_can_start_after_event_was_archived_without_it(client):
    from app.announcements import dispatch_due

    headers, event, path, _ = closing_event(client)
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    dispatch_due(
        client.app.state.engine, lambda guild, channel: client.app.state.discord
    )
    assert client.post(path + "/archive", headers=headers).status_code == 200
    first = client.post(path + "/discord-messages/delete", headers=headers)
    assert first.status_code == 200
    assert first.json()["discord_cleanup_remaining"] == 0
    last = client.post(path + "/discord-messages/delete", headers=headers)
    assert last.json()["discord_cleanup_remaining"] == 0
    assert last.json()["discord_url"] is None


def test_archive_cleanup_waits_for_queued_announcements(client):
    from app.announcements import dispatch_due

    headers, event, path, _ = closing_event(client)
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    archived = client.post(
        path + "/archive?delete_discord_messages=true", headers=headers
    )
    assert archived.status_code == 200
    assert archived.json()["archived_at"] is not None
    assert archived.json()["discord_cleanup_retry_after"] == 2
    client.app.state.discord.at.return_value.delete_poll.assert_not_called()
    dispatch_due(
        client.app.state.engine, lambda guild, channel: client.app.state.discord
    )
    first = client.post(path + "/discord-messages/delete", headers=headers)
    assert first.json()["discord_cleanup_remaining"] == 0


def test_assigned_signup_message_can_be_deleted_later(client):
    headers, event, path, _ = closing_event(client)
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    deleted = client.post(path + "/signup-message/delete", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["discord_url"] is None
    assert (
        client.post(path + "/signup-message/delete", headers=headers).status_code == 200
    )
    client.app.state.discord.at.return_value.delete_poll.assert_called_once_with(
        "message"
    )


def test_draft_cannot_be_archived(client):
    headers = login(client)
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    assert (
        client.post(f"/api/events/{event['id']}/archive", headers=headers).status_code
        == 409
    )
    assert (
        client.post("/api/events/missing/archive", headers=headers).status_code == 404
    )


@pytest.mark.parametrize("enabled", [True, False])
def test_automatic_weight_adjustment_once_per_draw_and_setting_scope(client, enabled):
    from app.models import AssignmentPreference, PlayerProfile

    headers, event, path, _ = closing_event(client)
    assert client.get("/api/settings/assignment").json() == {
        "automatic_weight_adjustment": True,
        "announce_table_changes": False,
    }
    assert (
        client.put(
            "/api/settings/assignment",
            json={
                "automatic_weight_adjustment": enabled,
                "announce_table_changes": False,
            },
        ).status_code
        == 403
    )
    assert (
        client.put(
            "/api/settings/assignment",
            headers=headers,
            json={
                "automatic_weight_adjustment": enabled,
                "announce_table_changes": False,
            },
        ).status_code
        == 200
    )
    assert (
        client.get("/api/settings/assignment").json()["automatic_weight_adjustment"]
        is enabled
    )
    with DBSession(client.app.state.engine) as db:
        db.add(
            AssignmentPreference(
                scope_key="user:other",
                automatic_weight_adjustment=not enabled,
                announce_table_changes=True,
            )
        )
        db.add(
            PlayerProfile(
                guild_id="guild",
                discord_id="1",
                discord_name="Mary",
                real_name="Display",
                weighting=1.25,
            )
        )
        db.add(
            PlayerProfile(
                guild_id="other", discord_id="1", discord_name="Other", weighting=2.0
            )
        )
        db.commit()
    discord = client.app.state.discord
    discord.poll_message.return_value = closing_message(finalized=False)
    assert client.post(path + "/close", headers=headers).status_code == 202
    with DBSession(client.app.state.engine) as db:
        assert db.get(PlayerProfile, ("guild", "1")).weighting == 1.25
    # The setting is captured at the start of this closure, just like input weights.
    client.put(
        "/api/settings/assignment",
        headers=headers,
        json={
            "automatic_weight_adjustment": not enabled,
            "announce_table_changes": False,
        },
    )
    discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    run = client.get(path + "/assignments").json()
    assert run["snapshot"]["automatic_weight_adjustment"] is enabled

    def current():
        with DBSession(client.app.state.engine) as db:
            return {
                p.discord_id: p.weighting
                for p in db.query(PlayerProfile).filter_by(guild_id="guild")
            }

    weights = current()
    for player in run["snapshot"]["players"]:
        original = 1.25 if player["id"] == "1" else 1.0
        if enabled:
            delta = -0.1 if player["id"] in run["result"]["assignments"] else 0.1
            assert weights[player["id"]] == pytest.approx(original + delta)
        elif player["id"] == "1":
            assert weights[player["id"]] == original
        else:
            assert player["id"] not in weights
    assert client.post(path + "/close", headers=headers).status_code == 200
    client.post(
        path + "/announcement/retry", headers=headers, json={"confirm_repost": False}
    )
    client.post(path + "/archive", headers=headers)
    assert current() == weights
    with DBSession(client.app.state.engine) as db:
        assert db.get(PlayerProfile, ("other", "1")).weighting == 2.0
        assert (
            db.get(AssignmentPreference, "user:other").automatic_weight_adjustment
            is not enabled
        )
        assert db.get(PlayerProfile, ("guild", "1")).real_name == "Display"


def test_weight_adjustment_clamps_and_updates_test_profiles(client):
    from app.models import PlayerProfile

    headers = login(client)
    body = event_body()
    body["tables"][0]["capacity"] = 1
    event = client.post("/api/events", headers=headers, json=body).json()
    path = f"/api/events/{event['id']}"
    client.post(path + "/test-users", headers=headers, json={"players": 2})
    players = client.get(path + "/signups").json()[0]["players"]
    client.put(
        f"/api/players/{players[0]['id']}",
        headers=headers,
        json={"real_name": "Volunteer", "weighting": 0.1, "guaranteed_seat": True},
    )
    client.put(
        f"/api/players/{players[1]['id']}",
        headers=headers,
        json={"real_name": "Waiting", "weighting": 10},
    )
    client.post(path + "/publish", headers=headers)
    discord = client.app.state.discord
    discord.table_signups.return_value = [{"name": "Clocktower", "players": []}]
    discord.poll_message.return_value = {
        "poll": {
            "expiry": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
            "answers": [
                {"answer_id": 9, "poll_media": {"text": "Clocktower · 1 seats"}}
            ],
            "results": {"is_finalized": True, "answer_counts": []},
        }
    }
    discord.voter_users.return_value = []
    assert client.post(path + "/close", headers=headers).status_code == 200
    with DBSession(client.app.state.engine) as db:
        assert db.get(PlayerProfile, ("guild", players[0]["id"])).weighting == 0.1
        assert db.get(PlayerProfile, ("guild", players[1]["id"])).weighting == 10


@pytest.mark.parametrize("saved_connection", [True, False])
def test_disconnect_blocks_legacy_fallback_preserves_data_and_allows_reconnect(
    client, saved_connection
):
    from app.models import Event, GuildSettings, PlayerProfile, UserSettings

    headers = login(client)
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    with DBSession(client.app.state.engine) as db:
        if saved_connection:
            db.add(
                UserSettings(
                    user_id="owner",
                    guild_id="guild",
                    guild_name="Server",
                    channel_id="channel",
                    channel_name="games",
                )
            )
        db.add(
            UserSettings(
                user_id="other",
                guild_id="guild",
                guild_name="Server",
                channel_id="channel",
                channel_name="games",
            )
        )
        db.add(
            PlayerProfile(
                guild_id="guild",
                discord_id="123",
                discord_name="Mary",
                real_name="Display",
                weighting=1.2,
            )
        )
        db.add(GuildSettings(guild_id="guild", automatic_weight_adjustment=False))
        db.commit()
    assert client.get("/api/me").json()["needs_setup"] is False
    assert client.delete("/api/settings").status_code == 403
    assert client.get("/api/settings").json()["selection"] is not None
    assert client.delete("/api/settings", headers=headers).status_code == 204
    assert client.delete("/api/settings", headers=headers).status_code == 204
    assert client.get("/api/settings").json()["selection"] is None
    assert client.get("/api/me").json()["needs_setup"] is True
    assert client.get("/api/events").status_code == 409
    assert client.get("/api/settings/assignment").status_code == 409
    with DBSession(client.app.state.engine) as db:
        assert db.get(Event, event["id"]) is not None
        assert db.get(PlayerProfile, ("guild", "123")).weighting == 1.2
        assert db.get(GuildSettings, "guild").automatic_weight_adjustment is False
        assert db.get(UserSettings, "other").disconnected is False
    headers = login(client)
    assert client.get("/api/me").json()["needs_setup"] is True
    client.app.state.discord.destination_channels.return_value = (
        "Reconnected Server",
        [{"id": "101", "name": "games"}],
    )
    assert (
        client.put(
            "/api/settings",
            headers=headers,
            json={"guild_id": "100", "channel_id": "101"},
        ).status_code
        == 200
    )
    assert client.get("/api/me").json()["needs_setup"] is False
    assert client.get("/api/settings").json()["selection"]["guild_id"] == "100"
    with DBSession(client.app.state.engine) as db:
        assert db.get(UserSettings, "owner").disconnected is False
    client.app.state.discord.delete_poll.assert_not_called()


def test_connect_callback_saves_authorized_server_before_channel_selection(client):
    headers = login(client)
    client.delete("/api/settings", headers=headers)
    response = client.get("/api/auth/connect", follow_redirects=False)
    params = parse_qs(urlparse(response.headers["location"]).query)
    assert set(params["scope"][0].split()) == {"identify", "guilds", "bot"}
    assert params["response_type"] == ["code"]
    assert params["redirect_uri"] == ["http://localhost:5180/api/auth/callback"]
    assert params["integration_type"] == ["0"]
    assert "permissions" in params
    state = params["state"][0]
    discord = client.app.state.discord
    discord.identity.return_value = {
        "id": "owner",
        "username": "organizer",
        "authorized_guild": {"id": "100"},
        "guilds": [{"id": "100", "name": "Chosen", "owner": True}],
    }
    discord.manager_context.return_value = (
        {"id": "100", "name": "Chosen Server"},
        {},
        [],
    )
    callback = client.get(
        f"/api/auth/callback?state={state}&code=connected&guild_id=100",
        follow_redirects=False,
    )
    assert callback.status_code == 307
    assert callback.headers["location"] == "http://localhost:5180/#/settings"
    selection = client.get("/api/settings").json()["selection"]
    assert selection == {
        "guild_id": "100",
        "guild_name": "Chosen Server",
        "channel_id": "",
        "channel_name": "",
    }
    assert client.get("/api/settings").json()["disconnected"] is False
    assert client.get("/api/me").json()["needs_setup"] is True
    assert client.get("/api/events").status_code == 409
    assert client.get("/api/settings/assignment").status_code == 200
    # Reload/sign-in retains the authorized server even before choosing a channel.
    headers = login(client)
    assert client.get("/api/settings").json()["selection"] == selection
    discord.destination_channels.return_value = (
        "Chosen Server",
        [{"id": "101", "name": "games"}],
    )
    assert (
        client.put(
            "/api/settings",
            headers=headers,
            json={"guild_id": "100", "channel_id": "101"},
        ).status_code
        == 200
    )
    assert client.get("/api/me").json()["needs_setup"] is False
    assert client.get("/api/settings").json()["selection"]["channel_id"] == "101"
    discord.manager_context.assert_any_call("owner", "100")


@pytest.mark.parametrize(
    "failure",
    ["wrong-account", "wrong-server", "no-permission", "missing-server", "cancelled"],
)
def test_failed_connection_does_not_save_or_replace_connection(client, failure):
    login(client)
    response = client.get("/api/auth/connect", follow_redirects=False)
    state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
    previous = client.get("/api/settings").json()["selection"]
    discord = client.app.state.discord
    discord.identity.return_value = {
        "id": "other" if failure == "wrong-account" else "owner",
        "username": "organizer",
        "authorized_guild": {} if failure == "missing-server" else {"id": "100"},
    }
    discord.manager_context.return_value = ({"id": "100", "name": "Server"}, {}, [])
    if failure == "no-permission":
        discord.manager_context.side_effect = HTTPException(403, "Not a manager")
    code = "" if failure == "cancelled" else "connected"
    hint = "200" if failure == "wrong-server" else ""
    callback = client.get(
        f"/api/auth/callback?state={state}&code={code}&guild_id={hint}",
        follow_redirects=False,
    )
    assert callback.status_code in (400, 403)
    assert client.get("/api/settings").json()["selection"] == previous
    client.cookies.set("oauth_state", state, path="/api")
    assert client.get(f"/api/auth/callback?state={state}&code=retry").status_code == 400


def test_connect_state_is_bound_to_initiating_session_and_requires_sign_in(client):
    assert client.get("/api/auth/connect", follow_redirects=False).status_code == 401
    login(client)
    response = client.get("/api/auth/connect", follow_redirects=False)
    state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
    from app.models import Session as StoredSession

    with DBSession(client.app.state.engine) as db:
        session = db.get(StoredSession, digest(client.cookies.get("session")))
        session.user_id = "another-user"
        db.commit()
    client.app.state.discord.identity.reset_mock()
    callback = client.get(
        f"/api/auth/callback?state={state}&code=approved&guild_id=100",
        follow_redirects=False,
    )
    assert callback.status_code == 403
    client.app.state.discord.identity.assert_not_called()


def test_connect_verifies_guild_hint_when_token_omits_guild(client):
    login(client)
    response = client.get("/api/auth/connect", follow_redirects=False)
    state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
    discord = client.app.state.discord
    discord.identity.return_value = {"id": "owner", "username": "Organizer"}
    discord.manager_context.return_value = (
        {"id": "200", "name": "Verified Server"},
        {},
        [],
    )
    callback = client.get(
        f"/api/auth/callback?state={state}&code=approved&guild_id=200",
        follow_redirects=False,
    )
    assert callback.status_code == 307
    assert client.get("/api/settings").json()["selection"]["guild_id"] == "200"
    discord.manager_context.assert_called_once_with("owner", "200")
