"""Promotion preferences are scoped and older clients cannot reset them."""

from flow_helpers import login


def test_dm_preference_is_default_on_scoped_and_preserved_when_omitted(client):
    headers = login(client)
    assert (
        client.get("/api/settings/assignment").json()["dm_waitlist_promotions"] is True
    )
    body = {
        "automatic_weight_adjustment": True,
        "announce_table_changes": False,
        "dm_waitlist_promotions": True,
    }
    assert (
        client.put("/api/settings/assignment", headers=headers, json=body).json()[
            "dm_waitlist_promotions"
        ]
        is True
    )
    legacy = {"automatic_weight_adjustment": False, "announce_table_changes": False}
    assert (
        client.put("/api/settings/assignment", headers=headers, json=legacy).json()[
            "dm_waitlist_promotions"
        ]
        is True
    )
    org = client.post(
        "/api/organizations", headers=headers, json={"name": "DM Settings"}
    ).json()
    client.put(
        "/api/organizations/selection",
        headers=headers,
        json={"organization_id": org["id"]},
    )
    assert (
        client.get("/api/settings/assignment").json()["dm_waitlist_promotions"] is True
    )
    client.put(
        "/api/settings/assignment",
        headers=headers,
        json={**body, "dm_waitlist_promotions": False},
    )
    client.put(
        "/api/organizations/selection", headers=headers, json={"organization_id": None}
    )
    assert (
        client.get("/api/settings/assignment").json()["dm_waitlist_promotions"] is True
    )
