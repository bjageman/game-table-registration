import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest
from fastapi import HTTPException
from signup_helpers import custom_client as custom_client
from signup_helpers import publish
from sqlalchemy.orm import Session

from app.discord import reactions
from app.discord.gateway import SignupGateway
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
    embed = payload["embeds"][0]
    assert embed["fields"][0]["name"] == "1️⃣ A (0/1)"
    assert "Remove your reaction" in embed["description"]
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
    monkeypatch.setattr("app.discord.gateway.DiscordAPI", Mock(return_value=api))

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
    from flow_helpers import event_body, login

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


@pytest.mark.parametrize("failure", [None, "write", "closing", "disconnect"])
def test_closing_waits_for_queued_reactions_before_snapshot(
    custom_client, monkeypatch, failure
):
    from app.assignments.closing import close_and_assign

    client, _, config = custom_client
    _, event, _ = publish(custom_client, reaction=True)
    engine = client.app.state.engine
    with Session(engine) as db:
        db.get(Event, event["id"]).reaction_checkpoint = time.time()
        db.commit()
    if failure == "closing":
        monkeypatch.setattr(
            "app.assignments.closing._close_and_assign",
            Mock(side_effect=HTTPException(422, "Guarantee conflict")),
        )
    if failure == "write":
        monkeypatch.setattr(
            reactions, "change", Mock(side_effect=RuntimeError("Write failed"))
        )

    async def check():
        gateway = SignupGateway(engine, config)
        raw = SimpleNamespace(
            guild_id="guild",
            channel_id="channel",
            message_id="message",
            user_id=1,
            emoji=SimpleNamespace(id=None, name="1️⃣"),
            type=discord.ReactionType.normal,
            member=SimpleNamespace(bot=False, display_name="Player"),
        )
        key = ("guild", "channel", "message")
        queue = reactions.reaction_queue(engine)
        await gateway.reaction_lock.acquire()
        incoming = asyncio.create_task(gateway.on_raw_reaction_add(raw))
        closing = None
        try:
            await asyncio.sleep(0)
            assert queue.pending[key] == 1
            closing = asyncio.create_task(
                asyncio.to_thread(
                    close_and_assign,
                    engine,
                    client.app.state.discord,
                    event["id"],
                    "owner",
                    "channel",
                )
            )
            async with asyncio.timeout(3):
                while key not in queue.closing:
                    await asyncio.sleep(0)
            assert not closing.done()
            assert engine.pool.checkedout() == 0
            with Session(engine) as db:
                assert db.get(LotteryRun, event["id"]) is None
            late = SimpleNamespace(**{**raw.__dict__, "user_id": 2})
            late_task = asyncio.create_task(gateway.on_raw_reaction_add(late))
            await asyncio.sleep(0)
            assert not late_task.done()
            disconnecting = None
            if failure == "disconnect":
                disconnecting = asyncio.create_task(gateway.on_disconnect())
                await asyncio.sleep(0)
                assert queue.connection_changes == 1
            gateway.reaction_lock.release()
            await incoming
            if disconnecting:
                await disconnecting
            if failure:
                with pytest.raises(HTTPException) as error:
                    await asyncio.wait_for(closing, 3)
                assert error.value.status_code == (422 if failure == "closing" else 409)
                with Session(engine) as db:
                    assert db.get(LotteryRun, event["id"]) is None
            else:
                assert await asyncio.wait_for(closing, 3)
                with Session(engine) as db:
                    run = db.get(LotteryRun, event["id"])
                    assert [player["id"] for player in run.snapshot["players"]] == ["1"]
            await asyncio.wait_for(late_task, 3)
            if failure == "closing":
                assert saved(client, event, "2") == ["A"]
            assert key not in queue.closing
        finally:
            if gateway.reaction_lock.locked():
                gateway.reaction_lock.release()
            await incoming
            if closing:
                await asyncio.gather(closing, return_exceptions=True)
            await gateway.close()

    asyncio.run(check())


def test_reaction_freeze_timeout_and_failure_release_the_gate():
    queue = reactions.ReactionQueue()
    key = ("guild", "channel", "message")
    with queue.track(key) as accepted:
        assert accepted
        with pytest.raises(HTTPException) as error:
            with queue.freeze(key, timeout=0):
                pytest.fail("A draw must not start while work is pending")
        assert error.value.status_code == 409
        assert key not in queue.closing
    assert not queue.pending
    with queue.freeze(key):
        with queue.track(key) as accepted:
            assert not accepted
        with queue.track(("guild", "channel", "another")) as accepted:
            assert accepted
        with pytest.raises(HTTPException):
            with queue.freeze(key):
                pass
    with queue.track(key) as accepted:
        assert accepted
