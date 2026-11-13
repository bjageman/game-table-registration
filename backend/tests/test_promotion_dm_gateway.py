"""Private promotion controls work after restart and only for their recipient."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest
from promotion_helpers import discord_client, queued
from sqlalchemy.orm import Session

from app import promotion_dms, withdrawals
from app.config import Settings
from app.gateway import SignupGateway
from app.models import EventWithdrawal, LotteryRun


def interaction(notice_id):
    return SimpleNamespace(
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
        assert withdrawals.current_result(db, db.get(LotteryRun, "event"))[
            "assignments"
        ] == {"3": "Table A"}


@pytest.mark.parametrize(
    "invalid", ["guild", "application", "author", "bot", "missing-message"]
)
def test_forged_dm_interactions_are_ignored(promotion_db, invalid):
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
        await gateway.close()

    asyncio.run(check())
    with Session(promotion_db) as db:
        assert db.get(EventWithdrawal, ("event", "2")) is None


def test_failed_acknowledgement_cannot_mutate_a_seat(promotion_db):
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
        await gateway.close()

    asyncio.run(check())
    with Session(promotion_db) as db:
        assert db.get(EventWithdrawal, ("event", "2")) is None
