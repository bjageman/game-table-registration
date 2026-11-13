"""Test population API integration coverage."""

import time
from datetime import UTC, datetime, timedelta

from flow_helpers import event_body, login
from sqlalchemy.orm import Session as DBSession


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
    assert "[TEST]" in str(discord.publish.call_args.args[0])
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
    assert (
        "[TEST]"
        in discord.send_announcement.call_args_list[0].args[1]["embeds"][0]["title"]
    )
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
