"""Connections API integration coverage."""

from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException
from flow_helpers import event_body, login
from sqlalchemy.orm import Session as DBSession

from app.security import digest


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


def test_organization_admin_disconnect_preserves_personal_connection(client):
    from app.models import Organization, OrganizationMember, UserSettings

    headers = login(client)
    created = client.post(
        "/api/organizations", headers=headers, json={"name": "Disconnect Crew"}
    )
    assert created.status_code == 201
    org_id = created.json()["id"]
    assert (
        client.put(
            "/api/organizations/selection",
            headers=headers,
            json={"organization_id": org_id},
        ).status_code
        == 200
    )
    with DBSession(client.app.state.engine) as db:
        db.add(
            UserSettings(
                user_id="owner",
                guild_id="personal",
                guild_name="Personal",
                channel_id="saved",
                channel_name="Saved",
                disconnected=False,
            )
        )
        db.commit()
    for role in ("editor", "user"):
        with DBSession(client.app.state.engine) as db:
            db.get(OrganizationMember, (org_id, "owner")).role = role
            db.commit()
        assert client.delete("/api/settings", headers=headers).status_code == 403
    with DBSession(client.app.state.engine) as db:
        db.get(OrganizationMember, (org_id, "owner")).role = "admin"
        db.commit()
    assert client.delete("/api/settings", headers=headers).status_code == 204
    settings = client.get("/api/settings").json()
    assert settings["disconnected"] is True
    assert settings["selection"] is None
    assert client.get("/api/me").json()["needs_setup"] is True
    assert client.get("/api/events").status_code == 409
    with DBSession(client.app.state.engine) as db:
        assert db.get(Organization, org_id).channel_id == ""
        personal = db.get(UserSettings, "owner")
        assert personal.channel_id == "saved"
        assert personal.disconnected is False


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
    assert client.get("/api/settings/assignment").status_code == 200
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


def test_organization_connection_is_independent_of_personal_and_other_orgs(client):
    from app.models import Organization, UserSettings

    headers = login(client)
    with DBSession(client.app.state.engine) as db:
        db.add(
            UserSettings(
                user_id="owner",
                guild_id="200",
                guild_name="Personal",
                channel_id="201",
                channel_name="personal",
                disconnected=False,
            )
        )
        db.commit()
    first = client.post(
        "/api/organizations", headers=headers, json={"name": "First"}
    ).json()["id"]
    second = client.post(
        "/api/organizations", headers=headers, json={"name": "Second"}
    ).json()["id"]
    client.put(
        "/api/organizations/selection", headers=headers, json={"organization_id": first}
    )
    assert client.get("/api/settings").json()["selection"] is None
    preferences = {
        "show_open_signup_players": False,
        "dm_waitlist_promotions": False,
        "timezone": None,
        "automatic_weight_adjustment": False,
        "announce_table_changes": True,
        "post_discord_updates_to_thread": False,
    }
    assert (
        client.put("/api/settings/assignment", headers=headers, json=preferences).json()
        == preferences
    )
    response = client.get("/api/auth/connect", follow_redirects=False)
    state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
    discord = client.app.state.discord
    discord.identity.return_value = {
        "id": "owner",
        "username": "organizer",
        "authorized_guild": {"id": "100"},
    }
    discord.manager_context.return_value = (
        {"id": "100", "name": "Organization Server"},
        {},
        [],
    )
    assert (
        client.get(
            f"/api/auth/callback?state={state}&code=connected&guild_id=100",
            follow_redirects=False,
        ).status_code
        == 307
    )
    headers["X-CSRF-Token"] = client.get("/api/me").json()["csrf"]
    assert client.get("/api/settings").json()["selection"]["guild_id"] == "100"
    assert client.get("/api/settings").json()["disconnected"] is False
    discord.bot_items.return_value = [
        {"id": "100", "name": "Organization Server"},
        {"id": "300", "name": "Inaccessible"},
    ]
    discord.manager_context.side_effect = HTTPException(403, "Manage Server required")
    assert client.get("/api/settings/guilds").json()["guilds"] == [
        {"id": "100", "name": "Organization Server"}
    ]
    discord.manager_context.side_effect = None
    discord.organization_channels.return_value = (
        "Organization Server",
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
    assert client.delete("/api/settings", headers=headers).status_code == 204
    assert client.get("/api/settings").json()["selection"] is None
    assert client.get("/api/settings/assignment").json() == preferences
    with DBSession(client.app.state.engine) as db:
        assert db.get(Organization, first).guild_id == ""
        assert db.get(Organization, second).guild_id == ""
        assert db.get(UserSettings, "owner").guild_id == "200"
        assert db.get(UserSettings, "owner").channel_id == "201"


@pytest.mark.parametrize("discord_status", [403, 404, 429, 500])
def test_server_list_skips_inaccessible_servers_but_reports_discord_outages(
    client, discord_status
):
    from app.discord_api import DiscordRequestError

    login(client)
    discord = client.app.state.discord
    discord.bot_items.return_value = [
        {"id": "100", "name": "Available"},
        {"id": "200", "name": "Other Server"},
    ]

    def manager_context(_user_id, guild_id):
        if guild_id == "200":
            raise DiscordRequestError(discord_status)
        return {"id": "100", "name": "Available"}, {}, []

    discord.manager_context.side_effect = manager_context
    response = client.get("/api/settings/guilds")
    if discord_status in (403, 404):
        assert response.status_code == 200
        assert response.json()["guilds"] == [{"id": "100", "name": "Available"}]
    else:
        assert response.status_code == 502
