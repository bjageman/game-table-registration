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
        "is_test": False,
        "guaranteed_seat": False,
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
    params = parse_qs(urlparse(data["install_url"]).query)
    assert params["scope"] == ["bot"]
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
    from app.models import Announcement

    headers, event, path, _ = closing_event(client)
    discord = client.app.state.discord
    discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    delivery = client.get(path + "/announcement").json()
    assert delivery["status"] == "sent"
    assert delivery["url"].endswith("/channel/announcement")
    channel, payload = discord.send_announcement.call_args.args
    assert channel == "channel"
    assert "Table Assignments" in payload["content"]
    assert payload["enforce_nonce"] is True
    assert payload["allowed_mentions"]["parse"] == []
    assert client.post(path + "/close", headers=headers).status_code == 200
    discord.send_announcement.assert_called_once()
    with DBSession(client.app.state.engine) as db:
        assert db.query(Announcement).filter_by(event_id=event["id"]).count() == 1


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
    assert discord.send_announcement.call_count == 2
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
    discord.find_announcement.return_value = "accepted-but-response-lost"
    with DBSession(client.app.state.engine) as db:
        db.query(Announcement).filter_by(event_id=event["id"]).update(
            {"next_attempt": 0}
        )
        db.commit()
    dispatch_due(client.app.state.engine, lambda guild, channel: discord)
    assert client.get(path + "/announcement").json()["status"] == "sent"
    discord.send_announcement.assert_called_once()
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
    assert retried.json()["status"] == "sent"
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
    for call in discord.send_announcement.call_args_list:
        payload = call.args[1]
        assert "[TEST]" in payload["content"]
        assert "Editable test name" not in payload["content"]
        assert "Updated Display" not in payload["content"]
        assert "<@test-" not in payload["content"]
        assert payload["allowed_mentions"]["users"] == []


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
    }
    client.put("/api/players/123", headers=headers, json={"real_name": "   "})
    assert client.get(path + "/signups").json()[0]["players"][0] == {
        "id": "123",
        "name": "MaryDiscord",
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
