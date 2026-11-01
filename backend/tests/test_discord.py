from unittest.mock import Mock, patch

import httpx
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


def test_signup_lookup_matches_answer_ids_and_replaces_removed_votes():
    api = DiscordAPI(Settings(_env_file=None, discord_channel_id="channel"))
    message = {
        "poll": {
            "answers": [
                {"answer_id": 42, "poll_media": {"text": "Table A · 8 seats"}},
                {"answer_id": 9, "poll_media": {"text": "Table B · 12 seats"}},
            ]
        }
    }
    api.bot = Mock(
        side_effect=[
            message,
            {"users": [{"id": "1", "username": "mary", "global_name": "Mary"}]},
            {"users": [{"id": "2", "username": "Dan"}]},
            message,
            {"users": []},
            {"users": [{"id": "2", "username": "Dan"}]},
        ]
    )
    tables = [{"name": "Table A", "capacity": 8}, {"name": "Table B", "capacity": 12}]
    first = api.table_signups("message", tables)
    assert first[0]["players"] == [{"id": "1", "name": "Mary"}]
    assert first[1]["players"] == [{"id": "2", "name": "Dan"}]
    assert api.bot.call_args_list[1].args[1].endswith("/message/answers/42")
    second = api.table_signups("message", tables)
    assert second[0]["players"] == []
    assert second[1]["players"] == first[1]["players"]


def test_signup_pagination_deduplicates_and_excludes_bots():
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
                    {"id": "100", "username": "player100"},
                    {"id": "101", "username": "bot", "bot": True},
                    {"id": "102", "username": "last"},
                ]
            },
        ]
    )
    players = api.voters("message", 42)
    assert len(players) == 101
    assert api.bot.call_args.kwargs["params"] == {"limit": 100, "after": "100"}


def test_signup_page_failure_does_not_return_partial_players():
    api = DiscordAPI(Settings(_env_file=None))
    api.bot = Mock(
        side_effect=[
            {"users": [{"id": str(i), "username": "player"} for i in range(1, 101)]},
            HTTPException(502, "Discord unavailable"),
        ]
    )
    with pytest.raises(HTTPException):
        api.voters("message", 9)


@pytest.mark.parametrize("status", [204, 404])
def test_delete_discord_poll_accepts_success_and_already_deleted(status):
    api = DiscordAPI(Settings(_env_file=None, discord_channel_id="channel"))
    with patch("app.discord_api.httpx.Client") as client:
        request = client.return_value.__enter__.return_value.request
        request.return_value = httpx.Response(
            status, request=httpx.Request("DELETE", "https://discord.com/test")
        )
        api.delete_poll("message")
        assert request.call_args.args == (
            "DELETE",
            "https://discord.com/api/v10/channels/channel/messages/message",
        )


def test_delete_discord_poll_failure_is_reported():
    api = DiscordAPI(Settings(_env_file=None))
    with patch("app.discord_api.httpx.Client") as client:
        client.return_value.__enter__.return_value.request.return_value = (
            httpx.Response(
                403, request=httpx.Request("DELETE", "https://discord.com/test")
            )
        )
        with pytest.raises(HTTPException) as error:
            api.delete_poll("message")
        assert error.value.status_code == 502


def test_channel_picker_respects_user_and_bot_overwrites():
    from app.connection_settings import POLL_PERMISSIONS

    api = DiscordAPI(Settings(_env_file=None))
    guild = {"id": "100", "owner_id": "other", "name": "Games"}
    roles = [
        {"id": "100", "permissions": str(1 << 10)},
        {"id": "manager", "permissions": "32"},
        {"id": "bot-role", "permissions": str(POLL_PERMISSIONS)},
    ]
    api.bot = Mock(
        side_effect=lambda method, path: {
            "/guilds/100": guild,
            "/guilds/100/members/user": {"roles": ["manager"]},
            "/users/@me": {"id": "bot"},
            "/guilds/100/members/bot": {"roles": ["bot-role"]},
        }[path]
    )
    api.bot_items = Mock(
        side_effect=lambda path: (
            roles
            if path.endswith("roles")
            else [
                {"id": "101", "name": "public", "type": 0},
                {
                    "id": "102",
                    "name": "hidden",
                    "type": 0,
                    "permission_overwrites": [
                        {"id": "user", "type": 1, "deny": str(1 << 10), "allow": "0"},
                    ],
                },
                {
                    "id": "103",
                    "name": "no-polls",
                    "type": 0,
                    "permission_overwrites": [
                        {
                            "id": "bot-role",
                            "type": 0,
                            "deny": str(1 << 49),
                            "allow": "0",
                        },
                    ],
                },
                {"id": "104", "name": "voice", "type": 2},
            ]
        )
    )
    assert api.destination_channels("user", "100") == (
        "Games",
        [{"id": "101", "name": "public"}],
    )
    roles[1]["permissions"] = "0"
    with pytest.raises(HTTPException) as error:
        api.destination_channels("user", "100")
    assert error.value.status_code == 403


def test_saved_destination_rejects_lost_channel_access():
    api = DiscordAPI(
        Settings(_env_file=None, discord_guild_id="100", discord_channel_id="101")
    )
    api.manager_context = Mock(
        return_value=(
            {"id": "100", "owner_id": "other"},
            {"roles": ["manager"]},
            [
                {"id": "100", "permissions": "1024"},
                {"id": "manager", "permissions": "32"},
            ],
        )
    )
    api.bot = Mock(
        return_value={
            "guild_id": "100",
            "permission_overwrites": [
                {"id": "user", "type": 1, "deny": "1024", "allow": "0"},
            ],
        }
    )
    with pytest.raises(HTTPException):
        api.authorize_destination("user")


def test_end_poll_uses_discord_expire_endpoint():
    api = DiscordAPI(Settings(_env_file=None, discord_channel_id="channel"))
    api.bot = Mock(return_value={})
    api.end_poll("message")
    api.bot.assert_called_once_with("POST", "/channels/channel/polls/message/expire")


def test_discord_rate_limit_delay_is_preserved():
    from app.discord_api import DiscordRequestError

    api = DiscordAPI(Settings(_env_file=None))
    with patch("app.discord_api.httpx.Client") as client:
        client.return_value.__enter__.return_value.request.return_value = (
            httpx.Response(
                429,
                json={"retry_after": 42.5},
                request=httpx.Request("POST", "https://discord.com/test"),
            )
        )
        with pytest.raises(DiscordRequestError) as error:
            api.send_announcement("channel", {"content": "test"})
        assert error.value.retry_after == 42.5
        assert not error.value.ambiguous


def test_reconcile_announcement_requires_our_bot_and_matches_saved_payload():
    api = DiscordAPI(Settings(_env_file=None))
    api.bot = Mock(return_value={"id": "bot"})
    api.bot_items = Mock(
        return_value=[
            {
                "id": "1",
                "author": {"id": "other"},
                "nonce": "nonce",
                "content": "saved",
            },
            {"id": "2", "author": {"id": "bot"}, "content": "saved"},
        ]
    )
    assert (
        api.find_announcement("channel", {"content": "saved", "nonce": "nonce"}, 0)
        == "2"
    )
