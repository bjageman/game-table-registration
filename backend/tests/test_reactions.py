import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest
from sqlalchemy.orm import Session
from test_signups import custom_client as custom_client
from test_signups import publish

from app import reactions
from app.gateway import SignupGateway
from app.models import Event, LotteryRun, TableSignup


def saved(client, event, user="1"):
    with Session(client.app.state.engine) as db:
        row = db.get(TableSignup, (event["id"], user))
        return list(row.choices) if row else []


def test_numbered_publication_seeds_only_listed_tables(custom_client):
    client, _, _ = custom_client
    _, event, _ = publish(custom_client, reaction=True)
    assert event["signup_mode"] == "reactions"
    payload = client.app.state.discord.publish.call_args.args[0]
    assert "1️⃣ A" in payload["content"] and "2️⃣ B" in payload["content"]
    assert "Remove your reaction" in payload["content"]
    assert "components" not in payload and "poll" not in payload
    client.app.state.discord.seed_reactions.assert_called_once_with(
        "message", ["1️⃣", "2️⃣"]
    )


def test_add_remove_multiple_tables_and_duplicates(custom_client):
    client, _, _ = custom_client
    headers, event, path = publish(custom_client, reaction=True)
    engine = client.app.state.engine
    for emoji in ("1️⃣", "2️⃣", "1️⃣"):
        reactions.change(engine, event["id"], emoji, "1", "Player", True, time.time())
    assert saved(client, event) == ["A", "B"]
    rows = client.get(path + "/signups", headers=headers).json()
    assert [p["id"] for p in rows[0]["players"]] == ["1"]
    reactions.change(engine, event["id"], "1️⃣", "1", "", False, time.time())
    assert saved(client, event) == ["B"]
    reactions.change(engine, event["id"], "2️⃣", "1", "", False, time.time())
    assert saved(client, event) == []


def test_clear_emoji_and_all_reactions(custom_client):
    client, _, _ = custom_client
    _, event, _ = publish(custom_client, reaction=True)
    engine = client.app.state.engine
    for user in ("1", "2"):
        for emoji in ("1️⃣", "2️⃣"):
            reactions.change(
                engine, event["id"], emoji, user, "Player", True, time.time()
            )
    reactions.change(engine, event["id"], "1️⃣", None, "", False, time.time())
    assert saved(client, event) == saved(client, event, "2") == ["B"]
    reactions.change(engine, event["id"], None, None, "", False, time.time())
    assert saved(client, event) == saved(client, event, "2") == []


@pytest.mark.parametrize("mode", ["expired", "closing", "assigned", "unlisted"])
def test_late_closed_and_unlisted_reactions_do_not_change_choices(custom_client, mode):
    client, _, _ = custom_client
    _, event, _ = publish(custom_client, reaction=True)
    engine = client.app.state.engine
    reactions.change(engine, event["id"], "1️⃣", "1", "Player", True, time.time())
    with Session(engine) as db:
        record = db.get(Event, event["id"])
        if mode == "expired":
            record.closes_at = time.time() - 1
        elif mode != "unlisted":
            record.status = mode
        db.commit()
    reactions.change(
        engine,
        event["id"],
        "3️⃣" if mode == "unlisted" else "2️⃣",
        "1",
        "Player",
        True,
        time.time(),
    )
    assert saved(client, event) == ["A"]


def test_reconnect_replaces_stale_choices_before_deadline(custom_client):
    client, _, _ = custom_client
    _, event, _ = publish(custom_client, reaction=True)
    engine = client.app.state.engine
    reactions.change(engine, event["id"], "1️⃣", "1", "Player", True, time.time())
    reactions.mark_gap(engine)
    assert reactions.replace(
        engine, event["id"], [{"id": "2", "name": "New", "choices": ["B"]}], time.time()
    )
    assert saved(client, event) == []
    assert saved(client, event, "2") == ["B"]
    with Session(engine) as db:
        assert db.get(Event, event["id"]).reaction_error is None


def test_gap_crossing_deadline_blocks_lottery_instead_of_using_late_reactions(
    custom_client,
):
    client, _, _ = custom_client
    headers, event, path = publish(custom_client, reaction=True)
    engine = client.app.state.engine
    reactions.mark_gap(engine)
    with Session(engine) as db:
        db.get(Event, event["id"]).closes_at = time.time() - 1
        db.commit()
    assert not reactions.replace(
        engine,
        event["id"],
        [{"id": "1", "name": "Late", "choices": ["A"]}],
        time.time(),
    )
    assert client.post(path + "/close", headers=headers).status_code == 409
    with Session(engine) as db:
        assert db.get(LotteryRun, event["id"]) is None
    assert saved(client, event) == []


def test_reaction_selections_feed_existing_lottery(custom_client):
    client, _, _ = custom_client
    headers, event, path = publish(custom_client, reaction=True)
    engine = client.app.state.engine
    assert reactions.replace(
        engine,
        event["id"],
        [
            {"id": "1", "name": "Player", "choices": ["A", "B"]},
            {"id": "2", "name": "Other", "choices": ["B"]},
        ],
        time.time(),
    )
    response = client.post(path + "/close", headers=headers)
    assert response.status_code == 200, response.text
    with Session(engine) as db:
        run = db.get(LotteryRun, event["id"])
        assert len(run.result["assignments"]) == 2
        assert {p["id"]: p["choices"] for p in run.snapshot["players"]} == {
            "1": ["A", "B"],
            "2": ["B"],
        }
    client.app.state.discord.poll_message.assert_not_called()


def test_deadline_checkpoint_survives_restart_and_ignores_late_reactions(custom_client):
    client, _, _ = custom_client
    headers, event, path = publish(custom_client, reaction=True)
    engine = client.app.state.engine
    assert reactions.replace(
        engine,
        event["id"],
        [{"id": "1", "name": "Player", "choices": ["A"]}],
        time.time(),
    )
    with Session(engine) as db:
        db.get(Event, event["id"]).closes_at = time.time() - 1
        db.commit()
    reactions.checkpoint(engine, event["id"])
    reactions.mark_gap(engine)
    assert not reactions.pending(engine)
    reactions.change(engine, event["id"], "2️⃣", "1", "Player", True, time.time())
    assert saved(client, event) == ["A"]
    assert client.post(path + "/close", headers=headers).status_code == 200


def test_raw_gateway_reactions_work_without_message_cache_and_ignore_bots(
    custom_client,
):
    client, _, config = custom_client
    _, event, _ = publish(custom_client, reaction=True)

    async def check():
        gateway = SignupGateway(client.app.state.engine, config)
        raw = SimpleNamespace(
            guild_id="guild",
            channel_id="channel",
            message_id="message",
            user_id=1,
            emoji=SimpleNamespace(id=None, name="2️⃣"),
            type=discord.ReactionType.normal,
            member=SimpleNamespace(bot=False, display_name="Player"),
        )
        await gateway.on_raw_reaction_add(raw)
        assert saved(client, event) == ["B"]
        raw.member = None
        gateway.fetch_user = AsyncMock(
            side_effect=AssertionError("Remove needs no user fetch")
        )
        await gateway.on_raw_reaction_remove(raw)
        assert saved(client, event) == []
        raw.member = SimpleNamespace(bot=True, display_name="Bot")
        await gateway.on_raw_reaction_add(raw)
        assert saved(client, event) == []
        raw.member = SimpleNamespace(bot=False, display_name="Player")
        raw.channel_id = "other"
        await gateway.on_raw_reaction_add(raw)
        assert saved(client, event) == []
        await gateway.close()

    asyncio.run(check())


def test_gateway_recovery_uses_rest_then_marks_healthy(custom_client, monkeypatch):
    client, _, config = custom_client
    _, event, _ = publish(custom_client, reaction=True)
    api = Mock()
    api.at.return_value = api
    api.reaction_players.return_value = [
        {"id": "1", "name": "Player", "choices": ["B"]}
    ]
    monkeypatch.setattr("app.gateway.DiscordAPI", Mock(return_value=api))

    async def check():
        gateway = SignupGateway(client.app.state.engine, config)
        await gateway.sync_reactions()
        assert saved(client, event) == ["B"]
        await gateway.on_disconnect()
        with Session(client.app.state.engine) as db:
            assert db.get(Event, event["id"]).reaction_error
        await gateway.on_resumed()
        with Session(client.app.state.engine) as db:
            assert db.get(Event, event["id"]).reaction_error is None
        await gateway.close()

    asyncio.run(check())


def test_seeding_failure_holds_original_message_for_review(custom_client):
    from test_flow import event_body, login

    client, _, _ = custom_client
    headers = login(client)
    event = client.post("/api/events", json=event_body(), headers=headers).json()
    client.app.state.discord.seed_reactions.side_effect = RuntimeError("Network error")
    path = f"/api/events/{event['id']}/publish"
    assert client.post(path, headers=headers).status_code == 502
    assert client.post(path, headers=headers).status_code == 409
    with Session(client.app.state.engine) as db:
        record = db.get(Event, event["id"])
        assert record.status == "needs_review"
        assert record.message_id == "message"
    assert client.app.state.discord.publish.call_count == 1
