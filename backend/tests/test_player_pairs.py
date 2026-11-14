"""Reciprocal links, organization isolation, and immutable draw pairing."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

from flow_helpers import (
    closing_event,
    closing_message,
    connect_test_organization,
    login,
)
from sqlalchemy.orm import Session

from app.models import Event, PlayerProfile


def save_profiles(client, headers, ids=("1", "2", "3", "4")):
    for pid in ids:
        client.app.state.discord.bot.return_value = {"username": f"Player {pid}"}
        assert (
            client.put(
                f"/api/players/{pid}",
                headers=headers,
                json={"real_name": f"Name {pid}"},
            ).status_code
            == 200
        )


def link(client, headers, source, target, **body):
    return client.put(
        f"/api/players/{source}/partner",
        headers=headers,
        json={"partner_id": target, **body},
    )


def test_links_are_reciprocal_and_replacement_requires_confirmation(client):
    headers = login(client)
    save_profiles(client, headers)
    assert link(client, headers, "1", "2").json()["profile"]["partner"]["id"] == "2"
    assert client.get("/api/players/2").json()["partner"]["id"] == "1"
    lookup = {p["discord_id"]: p for p in client.get("/api/players").json()}
    assert lookup["1"]["partner"] == {"id": "2", "name": "Name 2"}
    assert lookup["2"]["partner"] == {"id": "1", "name": "Name 1"}
    assert link(client, headers, "3", "4").status_code == 200
    needs_confirmation = link(client, headers, "1", "3").json()
    assert needs_confirmation["confirmation_required"]
    assert "Name 3" in needs_confirmation["message"]
    assert "Name 4" in needs_confirmation["message"]
    assert client.get("/api/players/1").json()["partner"]["id"] == "2"
    assert client.get("/api/players/4").json()["partner"]["id"] == "3"
    assert link(client, headers, "1", "3", replace_partner_id="4").status_code == 200
    for pid, partner in (("1", "3"), ("3", "1")):
        assert client.get(f"/api/players/{pid}").json()["partner"]["id"] == partner
    for pid in ("2", "4"):
        assert client.get(f"/api/players/{pid}").json()["partner"] is None
    assert link(client, headers, "1", "1").status_code == 422
    assert link(client, headers, "1", "999").status_code == 404
    assert link(client, headers, "1", None).status_code == 200
    assert client.get("/api/players/3").json()["partner"] is None


def test_confirmation_is_repeated_if_target_partner_changed(client):
    headers = login(client)
    save_profiles(client, headers, ("1", "2", "3", "4", "5"))
    link(client, headers, "3", "4")
    assert link(client, headers, "1", "3").json()["replace_partner_id"] == "4"
    link(client, headers, "3", "5")
    response = link(client, headers, "1", "3", replace_partner_id="4").json()
    assert response["confirmation_required"]
    assert response["replace_partner_id"] == "5"
    assert client.get("/api/players/5").json()["partner"]["id"] == "3"


def test_concurrent_links_do_not_create_one_sided_pairs(client):
    headers = login(client)
    save_profiles(client, headers, ("1", "2", "3"))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda pid: link(client, headers, pid, "2"), ("1", "3"))
        )
    assert all(response.status_code == 200 for response in results)
    assert sum("confirmation_required" in response.json() for response in results) == 1
    partner = client.get("/api/players/2").json()["partner"]["id"]
    assert client.get(f"/api/players/{partner}").json()["partner"]["id"] == "2"
    other = "1" if partner == "3" else "3"
    assert client.get(f"/api/players/{other}").json()["partner"] is None


def test_same_discord_server_has_completely_independent_organization_profiles(client):
    headers = login(client)
    organizations = []
    for name in ("Crew A", "Crew B"):
        org = client.post(
            "/api/organizations", headers=headers, json={"name": name}
        ).json()
        connect_test_organization(client, org["id"])
        organizations.append(org["id"])

    def select(org):
        assert (
            client.put(
                "/api/organizations/selection",
                headers=headers,
                json={"organization_id": org},
            ).status_code
            == 200
        )

    select(organizations[0])
    save_profiles(client, headers, ("1", "2"))
    client.put(
        "/api/players/1",
        headers=headers,
        json={"weighting": 8, "guaranteed_seat": True},
    )
    link(client, headers, "1", "2")
    select(organizations[1])
    assert client.get("/api/players").json() == []
    second = client.get("/api/players/1").json()
    assert second["real_name"] == ""
    assert second["weighting"] == 5
    assert not second["guaranteed_seat"]
    assert second["partner"] is None
    save_profiles(client, headers, ("1",))
    assert link(client, headers, "1", "2").status_code == 404
    client.put(
        "/api/players/1",
        headers=headers,
        json={"weighting": 2, "real_name": "Different Name"},
    )
    select(organizations[0])
    first = client.get("/api/players/1").json()
    assert first["real_name"] == "Name 1"
    assert first["weighting"] == 8
    assert first["guaranteed_seat"]
    assert first["partner"]["id"] == "2"
    select(None)
    assert client.get("/api/players").json() == []


def test_draw_freezes_pair_and_adjusts_each_players_own_weight(client):
    headers, event, path, _ = closing_event(client, review=True)
    save_profiles(client, headers)
    with Session(client.app.state.engine) as db:
        db.get(Event, event["id"]).tables = [
            {"name": "A", "capacity": 2},
            {"name": "B", "capacity": 1},
        ]
        db.commit()
    client.put(
        "/api/players/1",
        headers=headers,
        json={"weighting": 8, "guaranteed_seat": True},
    )
    client.put("/api/players/2", headers=headers, json={"weighting": 2})
    link(client, headers, "1", "2")
    client.app.state.discord.table_signups.return_value = [
        {
            "name": "A",
            "players": [
                {"id": "1", "name": "Player 1"},
                {"id": "2", "name": "Player 2"},
                {"id": "3", "name": "Player 3"},
            ],
        },
        {
            "name": "B",
            "players": [
                {"id": "1", "name": "Player 1"},
                {"id": "4", "name": "Player 4"},
            ],
        },
    ]
    message = closing_message()
    message["poll"]["answers"][0]["poll_media"]["text"] = "A · 2 seats"
    client.app.state.discord.poll_message.return_value = message
    closed = client.post(path + "/close", headers=headers)
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "review"
    original = deepcopy(client.get(path + "/assignments").json())
    assert (
        original["result"]["assignments"]["1"]
        == original["result"]["assignments"]["2"]
        == "A"
    )
    link(client, headers, "1", "3")
    assert client.get(path + "/assignments").json() == original
    assert (
        client.post(path + "/assignments/approve", headers=headers).status_code == 200
    )
    assert client.get("/api/players/1").json()["weighting"] == 7.5
    assert client.get("/api/players/2").json()["weighting"] == 1.5
    assert not client.get("/api/players/2").json()["guaranteed_seat"]
    with Session(client.app.state.engine) as db:
        assert db.get(PlayerProfile, ("user:owner", "guild", "1")).partner_id == "3"


def test_guaranteed_pair_conflict_alerts_manager_and_waitlists_both(client):
    headers, _, path, _ = closing_event(client, review=True)
    save_profiles(client, headers, ("1", "2"))
    client.put("/api/players/1", headers=headers, json={"guaranteed_seat": True})
    link(client, headers, "1", "2")
    client.app.state.discord.table_signups.return_value = [
        {
            "name": "A",
            "players": [
                {"id": "1", "name": "Mary"},
                {"id": "2", "name": "Dan"},
                {"id": "3", "name": "Shirley"},
            ],
        },
        {
            "name": "B",
            "players": [{"id": "1", "name": "Mary"}, {"id": "4", "name": "Carl"}],
        },
    ]
    client.app.state.discord.poll_message.return_value = closing_message()
    closed = client.post(path + "/close", headers=headers)
    assert closed.status_code == 200, closed.text
    assert closed.json()["pairing_warnings"]
    result = client.get(path + "/assignments").json()["current_result"]
    assert set(result["waitlist"]) == {"1", "2"}
    assert set(result["assignments"]) == {"3", "4"}
    for pid in ("1", "2"):
        assert (
            client.post(
                path + f"/assigned-players/{pid}", headers=headers, json={"table": "A"}
            ).status_code
            == 200
        )
    approved = client.post(path + "/assignments/approve", headers=headers)
    assert approved.status_code == 200
    assert approved.json()["pairing_warnings"] == []


def test_first_time_poll_participants_can_be_linked_before_the_first_draw(client):
    headers, _, path, _ = closing_event(client, review=True)
    client.app.state.discord.table_signups.return_value = [
        {
            "name": "A",
            "players": [{"id": "1", "name": "Alice"}, {"id": "2", "name": "Bob"}],
        },
        {"name": "B", "players": []},
    ]
    assert client.get("/api/players").json() == []
    assert client.get(path + "/signups").status_code == 200
    assert {player["discord_id"] for player in client.get("/api/players").json()} == {
        "1",
        "2",
    }
    linked = link(client, headers, "1", "2")
    assert linked.status_code == 200
    assert linked.json()["profile"]["partner"] == {"id": "2", "name": "Bob"}
    assert client.get("/api/players/2").json()["partner"] == {
        "id": "1",
        "name": "Alice",
    }
    with Session(client.app.state.engine) as db:
        from app.models import TableSignup

        assert all(not row.choices for row in db.query(TableSignup).all())
