"""Private promotion controls work after restart and only for their recipient."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest
from promotion_helpers import discord_client, queued
from sqlalchemy.orm import Session

from app.assignments import roster
from app.config import Settings
from app.discord import promotion_dms
from app.discord.gateway import SignupGateway
from app.models import EventWithdrawal, LotteryRun


def interaction(notice_id):
    return SimpleNamespace(
        id=9001,
        application_id=123,
        type=discord.InteractionType.component,
        guild_id=None,
        channel_id="private-channel",
        user=SimpleNamespace(id=2, bot=False),
        data={
            "custom_id": promotion_dms.BUTTON_PREFIX + notice_id,
            "component_type": 2,
        },
        message=SimpleNamespace(id="private-message", author=SimpleNamespace(id=123)),
        response=SimpleNamespace(defer=AsyncMock()),
        edit_original_response=AsyncMock(),
    )


def test_dm_button_withdraws_and_repeated_click_does_not_promote_twice(promotion_db):
    notice_id = queued(promotion_db)
    promotion_dms.dispatch_due(promotion_db, discord_client())

    async def check():
        gateway = SignupGateway(
            promotion_db, Settings(_env_file=None, discord_client_id="123")
        )
        first = interaction(notice_id)
        await gateway.on_interaction(first)
        first.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        assert (
            "You have withdrawn"
            in first.edit_original_response.call_args.kwargs["content"]
        )
        assert (
            first.edit_original_response.call_args.kwargs["allowed_mentions"].to_dict()[
                "parse"
            ]
            == []
        )
        duplicate = interaction(notice_id)
        await gateway.on_interaction(duplicate)
        assert (
            "no longer have a seat"
            in duplicate.edit_original_response.call_args.kwargs["content"]
        )
        await gateway.close()

    asyncio.run(check())
    with Session(promotion_db) as db:
        assert roster.build_current_roster(db, db.get(LotteryRun, "event"))[
            "assignments"
        ] == {"3": "Table A"}


@pytest.mark.parametrize(
    "invalid", ["guild", "application", "author", "bot", "missing-message"]
)
def test_forged_dm_interactions_are_ignored(promotion_db, invalid, caplog):
    notice_id = queued(promotion_db)
    promotion_dms.dispatch_due(promotion_db, discord_client())

    async def check():
        gateway = SignupGateway(
            promotion_db, Settings(_env_file=None, discord_client_id="123")
        )
        item = interaction(notice_id)
        if invalid == "guild":
            item.guild_id = "guild"
        elif invalid == "application":
            item.application_id = 999
        elif invalid == "author":
            item.message.author.id = 999
        elif invalid == "bot":
            item.user.bot = True
        else:
            item.message = None
        await gateway.on_interaction(item)
        item.response.defer.assert_not_awaited()
        reason = {
            "guild": "not_private",
            "application": "wrong_application",
            "author": "wrong_message_author",
            "bot": "bot_user",
            "missing-message": "missing_message",
        }[invalid]
        assert f"reason={reason}" in caplog.text
        assert f"notice_id={notice_id}" in caplog.text
        assert "interaction_id=9001" in caplog.text
        await gateway.close()

    asyncio.run(check())
    with Session(promotion_db) as db:
        assert db.get(EventWithdrawal, ("event", "2")) is None


def test_failed_acknowledgement_cannot_mutate_a_seat(promotion_db, caplog):
    notice_id = queued(promotion_db)
    promotion_dms.dispatch_due(promotion_db, discord_client())

    async def check():
        gateway = SignupGateway(
            promotion_db, Settings(_env_file=None, discord_client_id="123")
        )
        item = interaction(notice_id)
        item.response.defer.side_effect = discord.HTTPException(
            SimpleNamespace(status=503, reason="Unavailable"), "Unavailable"
        )
        await gateway.on_interaction(item)
        item.edit_original_response.assert_not_awaited()
        assert "acknowledgement failed" in caplog.text
        assert f"notice_id={notice_id}" in caplog.text
        assert "http_status=503" in caplog.text
        await gateway.close()

    asyncio.run(check())
    with Session(promotion_db) as db:
        assert db.get(EventWithdrawal, ("event", "2")) is None


@pytest.mark.parametrize("stage", ["processing", "response"])
def test_withdrawal_failures_include_correlated_ids_and_error_details(
    promotion_db, caplog, monkeypatch, stage
):
    notice_id = queued(promotion_db)
    promotion_dms.dispatch_due(promotion_db, discord_client())
    if stage == "processing":

        def fail(*args):
            raise RuntimeError("Simulated withdrawal failure")

        monkeypatch.setattr(
            "app.discord.gateway.player_changes.withdraw_from_promotion_dm", fail
        )

    async def check():
        gateway = SignupGateway(
            promotion_db, Settings(_env_file=None, discord_client_id="123")
        )
        item = interaction(notice_id)
        if stage == "response":
            item.edit_original_response.side_effect = discord.HTTPException(
                SimpleNamespace(status=503, reason="Unavailable"), "Unavailable"
            )
        await gateway.on_interaction(item)
        await gateway.close()

    asyncio.run(check())
    assert f"withdrawal {stage} failed" in caplog.text
    assert f"notice_id={notice_id}" in caplog.text
    assert "interaction_id=9001" in caplog.text
    assert "user_id=2" in caplog.text
    assert "channel_id=private-channel" in caplog.text
    assert "message_id=private-message" in caplog.text
    if stage == "processing":
        assert any(record.exc_info for record in caplog.records)
    else:
        assert "http_status=503" in caplog.text
    with Session(promotion_db) as db:
        # A response error occurs after the seat change committed, whereas a
        # processing error must leave the seat untouched.
        assert (db.get(EventWithdrawal, ("event", "2")) is not None) == (
            stage == "response"
        )
