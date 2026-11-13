"""Organizations API integration coverage."""

from fastapi import HTTPException
from flow_helpers import connect_test_organization, event_body, login


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
    connect_test_organization(client, org_id)
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
    connect_test_organization(client, org_id, "100", "101")
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
    assert client.delete("/api/settings", headers=owner).status_code == 204
    assert client.get("/api/settings").json()["disconnected"] is True
    discord.destination_channels.side_effect = None
    assert (
        client.put(
            "/api/settings",
            headers=owner,
            json={"guild_id": "100", "channel_id": "102"},
        ).status_code
        == 200
    )
    assert client.get("/api/settings").json()["disconnected"] is False
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
    assert client.delete("/api/settings", headers=second).status_code == 403

    discord.identity.return_value = {"id": "owner", "username": "organizer"}
    owner = login(client)
    client.put(
        "/api/organizations/selection", headers=owner, json={"organization_id": None}
    )
    assert client.get("/api/settings").json()["selection"]["channel_id"] == "101"


def test_assignment_settings_follow_selected_organization_and_admin_role(client):
    owner_headers = login(client)
    personal = {
        "show_open_signup_players": False,
        "review_assignments_before_discord": True,
        "dm_waitlist_promotions": False,
        "timezone": "America/Los_Angeles",
        "automatic_weight_adjustment": False,
        "announce_table_changes": True,
        "post_discord_updates_to_thread": False,
    }
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
    defaults = {
        "show_open_signup_players": True,
        "review_assignments_before_discord": True,
        "dm_waitlist_promotions": True,
        "timezone": None,
        "automatic_weight_adjustment": True,
        "announce_table_changes": True,
        "post_discord_updates_to_thread": True,
    }
    assert client.get("/api/settings/assignment").json() == defaults
    shared = {
        "show_open_signup_players": True,
        "review_assignments_before_discord": True,
        "dm_waitlist_promotions": False,
        "timezone": "Europe/London",
        "automatic_weight_adjustment": False,
        "announce_table_changes": False,
        "post_discord_updates_to_thread": True,
    }
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
    assert client.get("/api/me").json()["timezone"] == "Europe/London"
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
    assert client.get("/api/me").json()["timezone"] == "America/Los_Angeles"
