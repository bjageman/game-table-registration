from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.config import Settings
from app.discord_api import DiscordAPI


def test_member_roles_and_owner():
    api = DiscordAPI(
        Settings(_env_file=None, owner_discord_id="owner", moderator_role_ids="mod")
    )
    api.bot = Mock(return_value={"roles": []})
    api.authorize("owner")
    with pytest.raises(HTTPException) as error:
        api.authorize("stranger")
    assert error.value.status_code == 403
    api.bot.return_value = {"roles": ["mod"]}
    api.authorize("moderator")
    api.bot.side_effect = HTTPException(502, "Membership lookup failed")
    with pytest.raises(HTTPException):
        api.authorize("owner")


def test_wrong_channel_guild_cannot_post():
    api = DiscordAPI(Settings(_env_file=None, discord_guild_id="right"))
    api.bot = Mock(return_value={"guild_id": "wrong"})
    with pytest.raises(HTTPException):
        api.publish({})
    assert api.bot.call_count == 1


def test_voters_paginates_deduplicates_and_excludes_bots():
    api = DiscordAPI(Settings(_env_file=None, discord_channel_id="channel"))
    api.bot = Mock(
        side_effect=[
            {
                "users": [
                    {"id": str(i), "username": f"player{i}"} for i in range(1, 101)
                ]
            },
            {
                "users": [
                    {"id": "101", "username": "mary", "global_name": "Mary"},
                    {"id": "102", "username": "bot", "bot": True},
                ]
            },
        ]
    )
    players = api.voters("message", 9)
    assert len(players) == 101
    assert {"id": "101", "name": "Mary"} in players
    assert api.bot.call_args.kwargs["params"] == {"limit": 100, "after": "100"}
    assert api.bot.call_args.args[1].endswith("/message/answers/9")
