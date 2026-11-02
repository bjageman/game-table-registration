"""Exercise Discord signup logic without sending messages to Discord."""

import itertools
import os
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event as ThreadEvent
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_flow import event_body, login

from app.config import Settings
from app.main import create_app
from app.models import (
    Base,
    Event,
    LotteryRun,
    PlayerProfile,
    SignupInteraction,
    TableSignup,
)
from app.signups import handle


@pytest.fixture
def custom_client(tmp_path):
    settings = Settings(
        _env_file=None,
        announcement_worker_enabled=False,
        database_url=os.getenv("TEST_DATABASE_URL", f"sqlite:///{tmp_path}/custom.db"),
        discord_client_id="123",
        discord_client_secret="secret",
        discord_bot_token="token",
        discord_gateway_enabled=False,
        discord_guild_id="guild",
        discord_channel_id="channel",
        owner_discord_id="owner",
    )
    app = create_app(settings)
    Base.metadata.drop_all(app.state.engine)
    Base.metadata.create_all(app.state.engine)
    app.state.discord = Mock()
    app.state.discord.identity.return_value = {"id": "owner", "username": "organizer"}
    app.state.discord.publish.return_value = {"id": "message"}
    app.state.discord.send_announcement.return_value = {"id": "announcement"}
    with TestClient(app) as client:
        yield client, None, settings
    app.state.engine.dispose()


def dispatch(custom_client, payload):
    client, _, settings = custom_client
    try:
        return Response(200, json=handle(client.app.state.engine, settings, payload))
    except HTTPException as error:
        return Response(error.status_code, json={"detail": error.detail})


ids = itertools.count(1000)


def interaction(event, action="open", user="1", values=None):
    return {
        "id": str(next(ids)),
        "application_id": "123",
        "type": 3,
        "guild_id": "guild",
        "channel_id": "channel",
        "member": {"user": {"id": user, "username": f"Player {user}"}},
        "message": (
            {"id": "message"}
            if action == "open"
            else {"id": "private", "flags": 64, "author": {"id": "123"}}
        ),
        "data": {
            "custom_id": f"signup:{action}:{event['id']}",
            "component_type": 3 if action == "select" else 2,
            "values": ["0"] if values is None else values,
        },
    }


def publish(custom_client):
    client, _, _ = custom_client
    headers = login(client)
    body = {
        **event_body(),
        "tables": [{"name": "A", "capacity": 1}, {"name": "B", "capacity": 1}],
    }
    event = client.post("/api/events", json=body, headers=headers).json()
    result = client.post(f"/api/events/{event['id']}/publish", headers=headers)
    assert result.status_code == 200, result.text
    return headers, result.json(), f"/api/events/{event['id']}"


def test_custom_publication_and_duplicate_guard(custom_client):
    client, _, _ = custom_client
    headers, event, path = publish(custom_client)
    payload = client.app.state.discord.publish.call_args.args[0]
    assert "poll" not in payload
    assert "A · 1 seats" in payload["content"]
    assert "B · 1 seats" in payload["content"]
    assert "lottery entry" in payload["content"]
    assert payload["allowed_mentions"] == {"parse": []}
    assert (
        payload["components"][0]["components"][0]["custom_id"]
        == f"signup:open:{event['id']}"
    )
    assert event["signup_mode"] == "custom"
    assert event["closes_at"] == pytest.approx(time.time() + 86400, abs=5)
    assert client.post(path + "/publish", headers=headers).status_code == 409
    assert client.app.state.discord.publish.call_count == 1


def test_http_interactions_endpoint_is_removed(custom_client):
    client, _, _ = custom_client
    assert client.post("/api/discord/interactions", json={"type": 1}).status_code == 404


def test_players_choose_review_replace_and_withdraw_in_discord(custom_client):
    client, _, _ = custom_client
    headers, event, path = publish(custom_client)
    response = dispatch(custom_client, interaction(event)).json()
    assert response["type"] == 4
    assert response["data"]["flags"] == 64
    assert "Saved tables: None" in response["data"]["content"]
    choices = response["data"]["components"][0]["components"][0]
    assert choices["max_values"] == 2
    assert [o["label"] for o in choices["options"]] == ["A", "B"]
    saved = dispatch(
        custom_client, interaction(event, "select", values=["0", "1"])
    ).json()
    assert saved["type"] == 7  # Update only the private menu, never the shared message.
    assert "Saved tables: A, B" in saved["data"]["content"]
    dispatch(custom_client, interaction(event, "select", user="2", values=["1"]))
    reviewed = dispatch(custom_client, interaction(event)).json()
    assert all(
        o["default"]
        for o in reviewed["data"]["components"][0]["components"][0]["options"]
    )
    dispatch(custom_client, interaction(event, "select", values=["0"]))
    rows = client.get(path + "/signups", headers=headers).json()
    assert [p["id"] for p in rows[0]["players"]] == ["1"]
    assert [p["id"] for p in rows[1]["players"]] == ["2"]
    withdrawn = dispatch(custom_client, interaction(event, "withdraw")).json()
    assert "withdrawn from all tables" in withdrawn["data"]["content"]
    rows = client.get(path + "/signups", headers=headers).json()
    assert rows[0]["players"] == []
    assert [p["id"] for p in rows[1]["players"]] == ["2"]
    client.app.state.discord.table_signups.assert_not_called()
    with Session(client.app.state.engine) as db:
        assert db.get(TableSignup, (event["id"], "1")) is None


@pytest.mark.parametrize("values", [[], ["2"], ["-1"], ["0", "0"], [0], "0", [None]])
def test_invalid_choices_do_not_replace_saved_signup(custom_client, values):
    client, _, _ = custom_client
    _, event, _ = publish(custom_client)
    dispatch(custom_client, interaction(event, "select"))
    result = dispatch(custom_client, interaction(event, "select", values=values)).json()
    assert result["data"]["flags"] == 64
    assert "valid tables" in result["data"]["content"]
    with Session(client.app.state.engine) as db:
        assert db.get(TableSignup, (event["id"], "1")).choices == ["A"]


@pytest.mark.parametrize(
    "field,value", [("guild_id", "other"), ("channel_id", "other")]
)
def test_destination_scoping(custom_client, field, value):
    client, _, _ = custom_client
    _, event, _ = publish(custom_client)
    payload = interaction(event, "select")
    payload[field] = value
    assert (
        "no longer available"
        in dispatch(custom_client, payload).json()["data"]["content"]
    )
    with Session(client.app.state.engine) as db:
        assert db.get(TableSignup, (event["id"], "1")) is None


def test_controls_require_original_message_or_private_app_menu(custom_client):
    client, _, _ = custom_client
    _, event, _ = publish(custom_client)
    opening = interaction(event)
    opening["message"]["id"] = "another-message"
    assert (
        "original event" in dispatch(custom_client, opening).json()["data"]["content"]
    )
    for message in (
        {"flags": 0, "author": {"id": "123"}},
        {"flags": 64, "author": {"id": "456"}},
    ):
        selecting = interaction(event, "select")
        selecting["message"] = message
        assert (
            "original event"
            in dispatch(custom_client, selecting).json()["data"]["content"]
        )
    with Session(client.app.state.engine) as db:
        assert db.get(TableSignup, (event["id"], "1")) is None


def test_retries_do_not_restore_older_choices(custom_client):
    client, _, _ = custom_client
    _, event, _ = publish(custom_client)
    first = interaction(event, "select")
    response = dispatch(custom_client, first).json()
    dispatch(custom_client, interaction(event, "select", values=["1"]))
    assert dispatch(custom_client, first).json() == response
    with Session(client.app.state.engine) as db:
        assert db.get(TableSignup, (event["id"], "1")).choices == ["B"]
    withdrawal = interaction(event, "withdraw")
    dispatch(custom_client, withdrawal)
    dispatch(custom_client, interaction(event, "select"))
    dispatch(custom_client, withdrawal)
    with Session(client.app.state.engine) as db:
        assert db.get(TableSignup, (event["id"], "1")).choices == ["A"]


@pytest.mark.parametrize(
    "state", ["deadline", "closing", "assigned", "publishing", "needs_review", "draft"]
)
def test_closed_or_unpublished_events_reject_all_changes(custom_client, state):
    client, _, _ = custom_client
    _, event, _ = publish(custom_client)
    dispatch(custom_client, interaction(event, "select"))
    with Session(client.app.state.engine) as db:
        record = db.get(Event, event["id"])
        if state == "deadline":
            record.closes_at = time.time() - 1
        else:
            record.status = state
        db.commit()
    for action in ("open", "select", "withdraw"):
        result = dispatch(
            custom_client, interaction(event, action, values=["1"])
        ).json()
        assert "Signups are closed" in result["data"]["content"]
    with Session(client.app.state.engine) as db:
        assert db.get(TableSignup, (event["id"], "1")).choices == ["A"]


def test_custom_close_uses_saved_choices_once_and_announces(custom_client):
    client, _, _ = custom_client
    headers, event, path = publish(custom_client)
    dispatch(custom_client, interaction(event, "select", values=["0", "1"]))
    dispatch(custom_client, interaction(event, "select", user="2", values=["0"]))
    dispatch(custom_client, interaction(event, "select", user="3", values=["1"]))
    response = client.post(path + "/close", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "assigned"
    with Session(client.app.state.engine) as db:
        run = db.get(LotteryRun, event["id"])
        snapshot, result = run.snapshot, run.result
        assert {p["id"]: p["choices"] for p in snapshot["players"]} == {
            "1": ["A", "B"],
            "2": ["A"],
            "3": ["B"],
        }
        assert len(result["assignments"]) == 2
        assert len(result["waitlist"]) == 1
        for player in snapshot["players"]:
            expected = 0.9 if player["id"] in result["assignments"] else 1.1
            assert db.get(PlayerProfile, ("guild", player["id"])).weighting == expected
    assert client.post(path + "/close", headers=headers).status_code == 200
    with Session(client.app.state.engine) as db:
        assert db.get(LotteryRun, event["id"]).result == result
    client.app.state.discord.poll_message.assert_not_called()
    client.app.state.discord.end_poll.assert_not_called()
    client.app.state.discord.voter_users.assert_not_called()
    client.app.state.discord.close_signup_message.assert_called_with("message")
    assert client.app.state.discord.send_announcement.call_count == 1
    assert (
        "Signups are closed"
        in dispatch(custom_client, interaction(event, "select")).json()["data"][
            "content"
        ]
    )


def test_guarantee_conflict_allows_correction_without_losing_signups(custom_client):
    client, _, _ = custom_client
    headers, event, path = publish(custom_client)
    for user in ("1", "2"):
        dispatch(custom_client, interaction(event, "select", user=user))
    with Session(client.app.state.engine) as db:
        for user in ("1", "2"):
            db.add(
                PlayerProfile(guild_id="guild", discord_id=user, guaranteed_seat=True)
            )
        db.commit()
    assert client.post(path + "/close", headers=headers).status_code == 409
    with Session(client.app.state.engine) as db:
        assert db.get(Event, event["id"]).status == "open"
        assert db.get(LotteryRun, event["id"]) is None
    dispatch(custom_client, interaction(event, "select", user="2", values=["1"]))
    assert client.post(path + "/close", headers=headers).status_code == 200


def test_deleted_event_cleans_signups_and_rejects_old_controls(custom_client):
    client, _, _ = custom_client
    headers, event, path = publish(custom_client)
    dispatch(custom_client, interaction(event, "select"))
    assert client.delete(path, headers=headers).status_code == 204
    with Session(client.app.state.engine) as db:
        assert list(db.scalars(select(TableSignup))) == []
        assert list(db.scalars(select(SignupInteraction))) == []
    assert (
        "no longer available"
        in dispatch(custom_client, interaction(event)).json()["data"]["content"]
    )


def test_concurrent_players_keep_all_signups_and_duplicate_deliveries_are_safe(
    custom_client,
):
    client, _, _ = custom_client
    _, event, _ = publish(custom_client)
    payloads = [interaction(event, "select", user=str(i)) for i in range(1, 9)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(lambda p: dispatch(custom_client, p), payloads + [payloads[0]])
        )
    assert all(r.status_code == 200 for r in results)
    with Session(client.app.state.engine) as db:
        assert len(list(db.scalars(select(TableSignup)))) == 8
        assert len(list(db.scalars(select(SignupInteraction)))) == 8


def test_message_cleanup_failure_does_not_undo_assignments(custom_client):
    client, _, _ = custom_client
    headers, event, path = publish(custom_client)
    dispatch(custom_client, interaction(event, "select"))
    client.app.state.discord.close_signup_message.side_effect = HTTPException(
        502, "Discord unavailable"
    )
    assert client.post(path + "/close", headers=headers).status_code == 200
    assert (
        "Signups are closed"
        in dispatch(custom_client, interaction(event, "withdraw")).json()["data"][
            "content"
        ]
    )


def test_publication_does_not_require_public_key_or_public_endpoint(custom_client):
    _, event, _ = publish(custom_client)
    assert event["signup_mode"] == "custom"


def test_signups_and_receipts_survive_application_restart(custom_client):
    client, _, settings = custom_client
    _, event, _ = publish(custom_client)
    dispatch(custom_client, interaction(event, "select", values=["1"]))
    app = create_app(settings)
    with TestClient(app) as restarted:
        response = dispatch(
            (restarted, custom_client[1], settings), interaction(event)
        ).json()
        assert "Saved tables: B" in response["data"]["content"]
    app.state.engine.dispose()


def test_closing_claim_rejects_late_choices_before_snapshot(custom_client, monkeypatch):
    import app.closing as closing

    client, _, _ = custom_client
    headers, event, path = publish(custom_client)
    dispatch(custom_client, interaction(event, "select"))
    entered, release = ThreadEvent(), ThreadEvent()
    original = closing.signup_players

    def pause(db, record, weights):
        entered.set()
        assert release.wait(5)
        return original(db, record, weights)

    monkeypatch.setattr(closing, "signup_players", pause)
    with ThreadPoolExecutor(max_workers=1) as pool:
        closing_request = pool.submit(client.post, path + "/close", headers=headers)
        try:
            assert entered.wait(5)
            response = dispatch(
                custom_client, interaction(event, "select", values=["1"])
            )
            assert "Signups are closed" in response.json()["data"]["content"]
        finally:
            release.set()
        assert closing_request.result().status_code == 200
    with Session(client.app.state.engine) as db:
        assert db.get(LotteryRun, event["id"]).snapshot["players"][0]["choices"] == [
            "A"
        ]


def test_custom_signups_share_test_players_and_assignment_settings(custom_client):
    from app.models import GuildSettings

    client, _, _ = custom_client
    headers, event, path = publish(custom_client)
    dispatch(custom_client, interaction(event, "select"))
    assert (
        client.post(
            path + "/test-users", json={"players": 2}, headers=headers
        ).status_code
        == 200
    )
    with Session(client.app.state.engine) as db:
        db.add(GuildSettings(guild_id="guild", automatic_weight_adjustment=False))
        db.commit()
    rows = client.get(path + "/signups", headers=headers).json()
    assert "1" in {p["id"] for row in rows for p in row["players"]}
    assert any(p["id"].startswith("test-") for row in rows for p in row["players"])
    assert client.post(path + "/close", headers=headers).status_code == 200
    with Session(client.app.state.engine) as db:
        run = db.get(LotteryRun, event["id"])
        assert run.snapshot["is_test"] is True
        assert run.snapshot["automatic_weight_adjustment"] is False
        assert len(run.snapshot["players"]) == 3
        assert db.get(PlayerProfile, ("guild", "1")) is None


def test_legacy_poll_controls_cannot_create_database_signups(custom_client):
    client, _, _ = custom_client
    _, event, _ = publish(custom_client)
    with Session(client.app.state.engine) as db:
        db.get(Event, event["id"]).signup_mode = "poll"
        db.commit()
    response = dispatch(custom_client, interaction(event, "select"))
    assert "no longer available" in response.json()["data"]["content"]
    with Session(client.app.state.engine) as db:
        assert db.get(TableSignup, (event["id"], "1")) is None
