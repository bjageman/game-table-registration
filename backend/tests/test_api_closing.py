"""Closing API integration coverage."""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from flow_helpers import closing_event, closing_message, event_body, login
from sqlalchemy.orm import Session as DBSession


def test_close_signups_assigns_once_and_replays_saved_results(client):
    from app.assignments.lottery import assign
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
                scope_key="user:owner",
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
        db.get(PlayerProfile, ("user:owner", "guild", "2")).weighting = 9.0
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
    from app.assignments.closing import LEASE_SECONDS
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
