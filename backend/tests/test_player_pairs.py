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

from app.assignments.lottery import assign
from app.models import Event


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


def link(client, headers, source, *targets):
    return client.put(
        f"/api/players/{source}/pairings",
        headers=headers,
        json={"player_ids": list(targets)},
    )


def ids(client, pid):
    return {p["id"] for p in client.get(f"/api/players/{pid}").json()["pairings"]}


def test_preferences_are_reciprocal_not_transitive_and_removal_preserves_other_edges(
    client,
):
    headers = login(client)
    save_profiles(client, headers)
    assert link(client, headers, "1", "2", "3").status_code == 200
    assert ids(client, "1") == {"2", "3"}
    assert ids(client, "2") == ids(client, "3") == {"1"}
    assert link(client, headers, "2", "1", "4").status_code == 200
    assert link(client, headers, "1", "3", "3").status_code == 200
    assert ids(client, "1") == {"3"}
    assert ids(client, "2") == {"4"}
    assert ids(client, "4") == {"2"}
    lookup = {p["discord_id"]: p for p in client.get("/api/players").json()}
    assert lookup["1"]["pairings"] == [{"id": "3", "name": "Name 3"}]
    assert link(client, headers, "1", "1").status_code == 422
    assert link(client, headers, "1", "999").status_code == 404
    assert ids(client, "1") == {"3"}
    assert link(client, headers, "3").status_code == 200
    assert ids(client, "1") == set()
    assert link(client, {}, "1", "2").status_code == 403


def test_concurrent_preferences_preserve_both_reciprocal_edges(client):
    headers = login(client)
    save_profiles(client, headers, ("1", "2", "3"))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda pid: link(client, headers, pid, "2"), ("1", "3"))
        )
    assert all(response.status_code == 200 for response in results)
    assert ids(client, "2") == {"1", "3"}
    assert ids(client, "1") == ids(client, "3") == {"2"}


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
    assert second["pairings"] == []
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
    assert ids(client, "1") == {"2"}
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
    snapshot = original["snapshot"]
    assert snapshot["pairings"] == {"1": ["2"], "2": ["1"]}
    baseline = assign({**snapshot, "pairings": {}}, original["seed"])
    assert set(original["result"]["assignments"]) == set(baseline["assignments"])
    assert original["result"]["waitlist"] == baseline["waitlist"]
    assert "1" in original["result"]["assignments"]
    assert not closed.json()["pairing_warnings"]
    link(client, headers, "1", "3")
    assert client.get(path + "/assignments").json() == original
    assert (
        client.post(path + "/assignments/approve", headers=headers).status_code == 200
    )
    for pid, weight in (("1", 8), ("2", 2)):
        expected = weight - 0.5 if pid in baseline["assignments"] else weight + 0.5
        assert client.get(f"/api/players/{pid}").json()["weighting"] == expected
    assert not client.get("/api/players/2").json()["guaranteed_seat"]
    assert ids(client, "1") == {"3"}


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
    assert linked.json()["profile"]["pairings"] == [{"id": "2", "name": "Bob"}]
    assert client.get("/api/players/2").json()["pairings"] == [
        {"id": "1", "name": "Alice"}
    ]
    with Session(client.app.state.engine) as db:
        from app.models import TableSignup

        assert all(not row.choices for row in db.query(TableSignup).all())


def test_retry_keeps_original_frozen_preferences_after_profile_edits(client):
    from fastapi import HTTPException

    headers, event, path, users = closing_event(client, review=True)
    save_profiles(client, headers)
    link(client, headers, "1", "2")
    discord = client.app.state.discord
    discord.poll_message.return_value = closing_message()
    discord.voter_users.side_effect = HTTPException(502, "Discord unavailable")
    assert client.post(path + "/close", headers=headers).status_code == 502
    with Session(client.app.state.engine) as db:
        saved = db.get(Event, event["id"])
        seed = saved.close_seed
        assert saved.close_pairings == {"1": ["2"], "2": ["1"]}
    link(client, headers, "1", "3", "4")
    discord.voter_users.side_effect = lambda msg, answer: users[answer]
    assert client.post(path + "/close", headers=headers).status_code == 200
    draw = client.get(path + "/assignments").json()
    assert draw["snapshot"]["pairings"] == {"1": ["2"], "2": ["1"]}
    assert draw["seed"] == seed


def test_pending_close_retains_frozen_pair_snapshot(client):
    from app.assignments.lottery import VERSION

    headers, event, path, _ = closing_event(client, review=True)
    with Session(client.app.state.engine) as db:
        saved = db.get(Event, event["id"])
        saved.status = "closing"
        saved.close_pairs = {"1": "2", "2": "1"}
        db.commit()
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    draw = client.get(path + "/assignments").json()
    assert draw["version"] == VERSION
    assert draw["snapshot"]["pairs"] == {"1": "2", "2": "1"}
    assert "pairings" not in draw["snapshot"]
