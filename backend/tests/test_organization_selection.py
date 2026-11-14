"""A stale organization selection must not retain removed-member access."""

from flow_helpers import connect_test_organization, event_body, login
from sqlalchemy.orm import Session

from app.models import Organization, OrganizationMember


def test_removed_member_uses_personal_scope_consistently(client):
    headers = login(client)
    personal = client.post("/api/events", headers=headers, json=event_body()).json()
    org = client.post(
        "/api/organizations", headers=headers, json={"name": "Game Group"}
    ).json()
    connect_test_organization(client, org["id"], "org-guild", "org-channel")
    assert (
        client.put(
            "/api/organizations/selection",
            headers=headers,
            json={"organization_id": org["id"]},
        ).status_code
        == 200
    )
    with Session(client.app.state.engine) as db:
        db.delete(db.get(OrganizationMember, (org["id"], "owner")))
        db.commit()
    me = client.get("/api/me").json()
    assert me["organization"] is None
    client.app.state.discord.bot.reset_mock()
    settings = client.get("/api/settings").json()
    assert settings["organization_role"] is None
    assert settings["selection"]["guild_id"] == "guild"
    client.app.state.discord.bot.assert_not_called()
    assert [row["id"] for row in client.get("/api/events").json()] == [personal["id"]]
    assert client.delete("/api/settings", headers=headers).status_code == 204
    with Session(client.app.state.engine) as db:
        organization = db.get(Organization, org["id"])
        assert organization.guild_id == "org-guild"
        assert organization.channel_id == "org-channel"
