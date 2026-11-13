"""Auth API integration coverage."""

import time
from urllib.parse import parse_qs, urlparse

from fastapi import HTTPException
from flow_helpers import event_body, login
from sqlalchemy.orm import Session as DBSession

from app.models import Session
from app.security import digest


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
    assert "embeds" not in payload
    assert payload["content"].startswith("**Friday games**\nEvent:")
    assert "Bring friends" in payload["content"]
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


def test_general_timezone_is_validated_persisted_and_available_to_session(client):
    headers = login(client)
    path = "/api/settings/assignment"
    body = {
        "automatic_weight_adjustment": True,
        "announce_table_changes": False,
        "post_discord_updates_to_thread": False,
    }
    assert client.get(path).json()["timezone"] is None
    for invalid in ["Not/A_Timezone", "", "../UTC"]:
        assert (
            client.put(
                path, headers=headers, json={**body, "timezone": invalid}
            ).status_code
            == 422
        )
    assert (
        client.put(path, json={**body, "timezone": "America/New_York"}).status_code
        == 403
    )
    response = client.put(
        path, headers=headers, json={**body, "timezone": "America/New_York"}
    )
    assert response.status_code == 200
    assert response.json()["timezone"] == "America/New_York"
    assert client.get(path).json()["timezone"] == "America/New_York"
    assert client.get("/api/me").json()["timezone"] == "America/New_York"
    assert (
        client.put(path, headers=headers, json=body).json()["timezone"]
        == "America/New_York"
    )
    assert (
        client.put(path, headers=headers, json={**body, "timezone": None}).status_code
        == 200
    )
    assert client.get("/api/me").json()["timezone"] is None
