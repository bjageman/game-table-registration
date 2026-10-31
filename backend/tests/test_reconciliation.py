import asyncio
import copy
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.bot import TableBot
from app.config import Settings
from app.models import Base, Event
from app.players import player_status, withdraw
from app.reconciliation import reconcile_event
from app.recovery import RecoveryInput, recover_event


def setup(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/reconcile.db")
    Base.metadata.create_all(engine)
    config = Settings(_env_file=None, discord_guild_id="100", discord_channel_id="200")
    poll = {
        "expiry": (datetime.now(UTC) - timedelta(seconds=10)).isoformat(),
        "allow_multiselect": True,
        "answers": [
            {"answer_id": 9, "poll_media": {"text": "A · 15 seats"}},
            {"answer_id": 42, "poll_media": {"text": "B · 5 seats"}},
        ],
        "results": {
            "is_finalized": True,
            "answer_counts": [{"id": 9, "count": 101}, {"id": 42, "count": 1}],
        },
    }
    with Session(engine) as db:
        db.add(
            Event(
                id="event",
                guild_id="100",
                title="Games",
                starts_at=time.time() + 10000,
                duration_hours=1,
                tables=[{"name": "A", "capacity": 15}, {"name": "B", "capacity": 5}],
                status="closed",
                created_by="owner",
                message_id="123",
                closes_at=time.time() - 10,
                answers=poll["answers"],
            )
        )
        db.commit()
    discord = Mock()

    def bot(method, path, **kwargs):
        if path == "/users/@me":
            return {"id": "500"}
        if "/messages/" in path:
            return {
                "id": "123",
                "content": "Event ID: event",
                "author": {"id": "500"},
                "poll": copy.deepcopy(poll),
            }
        if path.endswith("/expire"):
            return {}
        if path.endswith("/answers/42"):
            return {"users": [{"id": "1"}]}
        after = int(kwargs["params"]["after"])
        return {
            "users": [
                {"id": str(n), "bot": n == 101}
                for n in range(after + 1, min(after + 101, 102))
            ]
        }

    discord.bot.side_effect = bot
    return engine, config, discord, poll


def test_reconciliation_paginates_deduplicates_and_freezes_snapshot(tmp_path):
    engine, config, discord, _ = setup(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(
            pool.map(
                lambda _: reconcile_event(engine, discord, config, "event"), range(2)
            )
        )
    with Session(engine) as db:
        event = db.get(Event, "event")
        assert event.status == "reconciled"
        assert len(event.voter_snapshot) == 100
        assert event.voter_snapshot[0] == {"user_id": "1", "tables": ["A", "B"]}
        snapshot = event.voter_snapshot
    calls = discord.bot.call_count
    reconcile_event(engine, discord, config, "event")
    assert discord.bot.call_count == calls
    withdraw(engine, "100", "1", "event")
    withdraw(engine, "100", "1", "event")
    assert player_status(engine, "100", "1", "event")["withdrawn"]
    with Session(engine) as db:
        assert db.get(Event, "event").voter_snapshot == snapshot
    with pytest.raises(HTTPException):
        withdraw(engine, "other", "1", "event")


def test_unfinalized_or_incomplete_results_never_commit_snapshot(tmp_path):
    engine, config, discord, poll = setup(tmp_path)
    poll["results"]["is_finalized"] = False
    reconcile_event(engine, discord, config, "event")
    with Session(engine) as db:
        event = db.get(Event, "event")
        assert event.status == "closed" and event.voter_snapshot is None
        assert event.reconcile_after > time.time()
        event.reconcile_after = 0
        db.commit()
    poll["results"]["is_finalized"] = True
    poll["results"]["answer_counts"][0]["count"] = 102
    reconcile_event(engine, discord, config, "event")
    with Session(engine) as db:
        assert db.get(Event, "event").voter_snapshot is None
        assert db.get(Event, "event").status == "closed"


def test_recovery_requires_explicit_late_vote_acceptance(tmp_path):
    engine, config, discord, poll = setup(tmp_path)
    poll["expiry"] = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    with Session(engine) as db:
        event = db.get(Event, "event")
        event.status = "needs_review"
        event.signup_closes_at = time.time() - 300
        db.commit()
    with pytest.raises(HTTPException, match="Deadline missed"):
        recover_event(
            engine,
            discord,
            config,
            "event",
            RecoveryInput(reason="Checked existing poll"),
            "owner",
        )
    recover_event(
        engine,
        discord,
        config,
        "event",
        RecoveryInput(reason="Accept later votes after outage", accept_late_votes=True),
        "owner",
    )
    with Session(engine) as db:
        event = db.get(Event, "event")
        assert event.status == "closed"
        assert event.recovery_audit[-1]["accepted_late_votes"]
        assert event.recovery_audit[-1]["actor"] == "owner"
    discord.publish.assert_not_called()


def test_changed_answers_are_held_for_review(tmp_path):
    engine, config, discord, poll = setup(tmp_path)
    poll["answers"][0]["poll_media"]["text"] = "Other table"
    reconcile_event(engine, discord, config, "event")
    with Session(engine) as db:
        assert db.get(Event, "event").status == "needs_review"
        assert db.get(Event, "event").voter_snapshot is None


def test_player_command_registration_uses_no_message_content_intent(tmp_path):
    config = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path}/bot.db",
        discord_guild_id="100",
    )
    bot = TableBot(config)
    bot.tree.sync = AsyncMock()
    asyncio.run(bot.setup_hook())
    import discord

    assert {
        command.name for command in bot.tree.get_commands(guild=discord.Object(id=100))
    } == {"signup_status", "withdraw_signup"}
    assert bot.intents.guild_polls and not bot.intents.message_content
    asyncio.run(bot.close())


def test_partial_retrieval_rate_limit_preserves_no_partial_snapshot(tmp_path):
    from app.discord_api import DiscordRateLimit

    engine, config, discord, _ = setup(tmp_path)
    original = discord.bot.side_effect

    def limited(method, path, **kwargs):
        if kwargs.get("params", {}).get("after") == "100":
            raise DiscordRateLimit(600)
        return original(method, path, **kwargs)

    discord.bot.side_effect = limited
    reconcile_event(engine, discord, config, "event")
    with Session(engine) as db:
        event = db.get(Event, "event")
        assert event.status == "closed" and event.voter_snapshot is None
        assert event.reconcile_after >= time.time() + 595
        event.status = "reconciling"
        event.operation_started_at = time.time() - 300
        db.commit()
    discord.bot.side_effect = original
    from app.reconciliation import tick

    tick(engine, discord, config)
    with Session(engine) as db:
        assert db.get(Event, "event").status == "reconciled"


def test_unlinked_recovery_requires_event_marker(tmp_path):
    engine, config, discord, _ = setup(tmp_path)
    original = discord.bot.side_effect

    def wrong_poll(method, path, **kwargs):
        result = original(method, path, **kwargs)
        if "/messages/" in path:
            result["content"] = "Different event"
        return result

    discord.bot.side_effect = wrong_poll
    with Session(engine) as db:
        event = db.get(Event, "event")
        event.status = "needs_review"
        event.message_id = None
        db.commit()
    with pytest.raises(HTTPException, match="recovery identifier"):
        recover_event(
            engine,
            discord,
            config,
            "event",
            RecoveryInput(message_id="123", reason="Check requested event"),
            "owner",
        )
    discord.publish.assert_not_called()


def test_live_votes_are_idempotent_preview_only(tmp_path):
    from sqlalchemy import select

    from app.live_votes import record_vote
    from app.models import LiveVote

    engine, config, _, _ = setup(tmp_path)
    with Session(engine) as db:
        db.get(Event, "event").status = "open"
        db.commit()
    for _ in range(2):
        record_vote(engine, config.discord_guild_id, "123", "1", 9, True)
    record_vote(engine, "other", "123", "1", 42, True)
    record_vote(engine, config.discord_guild_id, "123", "1", 999, True)
    with Session(engine) as db:
        assert len(list(db.scalars(select(LiveVote)))) == 1
        assert db.get(Event, "event").voter_snapshot is None
    record_vote(engine, config.discord_guild_id, "123", "1", 9, False)
    with Session(engine) as db:
        assert list(db.scalars(select(LiveVote))) == []
