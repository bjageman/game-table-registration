from typing import Any

import httpx
from fastapi import HTTPException

from app.config import Settings


class DiscordAPI:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def request_json(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            with httpx.Client(timeout=15) as client:
                response = client.request(
                    method, f"https://discord.com/api/v10{path}", **kwargs
                )
            # A retried deletion may find a poll that was already deleted.
            if method == "DELETE" and response.status_code == 404:
                return {}
            response.raise_for_status()
            if response.status_code == 204:
                return {}
            return response.json()
        except (httpx.HTTPError, ValueError):
            raise HTTPException(
                502, "Discord request failed. Please try again."
            ) from None

    def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        value = self.request_json(method, path, **kwargs)
        if not isinstance(value, dict):
            raise HTTPException(502, "Discord returned an invalid response")
        return value

    def request_items(self, path: str, **kwargs: Any) -> list[dict[str, Any]]:
        value = self.request_json("GET", path, **kwargs)
        if not isinstance(value, list) or any(
            not isinstance(row, dict) for row in value
        ):
            raise HTTPException(502, "Discord returned an invalid list")
        return value

    def bot_items(self, path: str) -> list[dict[str, Any]]:
        return self.request_items(
            path, headers={"Authorization": f"Bot {self.settings.discord_bot_token}"}
        )

    def at(self, guild_id: str, channel_id: str) -> "DiscordAPI":
        return DiscordAPI(
            self.settings.model_copy(
                update={"discord_guild_id": guild_id, "discord_channel_id": channel_id}
            )
        )

    def bot(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        return self.request(
            method,
            path,
            headers={"Authorization": f"Bot {self.settings.discord_bot_token}"},
            **kwargs,
        )

    def identity(self, code: str) -> dict[str, Any]:
        token = self.request(
            "POST",
            "/oauth2/token",
            data={
                "client_id": self.settings.discord_client_id,
                "client_secret": self.settings.discord_client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.settings.callback_url,
            },
        )
        headers = {"Authorization": f"Bearer {token['access_token']}"}
        user = self.request("GET", "/users/@me", headers=headers)
        user["guilds"] = self.request_items("/users/@me/guilds", headers=headers)
        return user

    def authorize(self, user_id: str) -> None:
        member = self.bot(
            "GET", f"/guilds/{self.settings.discord_guild_id}/members/{user_id}"
        )
        roles = set(self.settings.moderator_role_ids.split(",")) - {""}
        if user_id != self.settings.owner_discord_id and not roles.intersection(
            member.get("roles", [])
        ):
            raise HTTPException(403, "Moderator access is required.")

    def publish(self, payload: dict[str, Any]) -> dict[str, Any]:
        channel = self.bot("GET", f"/channels/{self.settings.discord_channel_id}")
        if channel.get("guild_id") != self.settings.discord_guild_id:
            raise HTTPException(400, "The signup channel belongs to another server.")
        return self.bot(
            "POST",
            f"/channels/{self.settings.discord_channel_id}/messages",
            json=payload,
        )

    def table_signups(
        self, message_id: str, tables: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        message = self.bot(
            "GET", f"/channels/{self.settings.discord_channel_id}/messages/{message_id}"
        )
        answers = message.get("poll", {}).get("answers", [])
        answer_ids = {
            a.get("poll_media", {}).get("text"): a.get("answer_id") for a in answers
        }
        rows = []
        for table in tables:
            label = f"{table['name']} · {table['capacity']} seats"
            answer_id = answer_ids.get(label)
            if not isinstance(answer_id, int):
                raise HTTPException(
                    502, "Could not match Discord poll answers to tables"
                )
            rows.append(
                {"name": table["name"], "players": self.voters(message_id, answer_id)}
            )
        return rows

    def voters(self, message_id: str, answer_id: int) -> list[dict[str, str]]:
        players: dict[str, dict[str, str]] = {}
        after = 0
        while True:
            response = self.bot(
                "GET",
                f"/channels/{self.settings.discord_channel_id}/polls/"
                f"{message_id}/answers/{answer_id}",
                params={"limit": 100, **({"after": str(after)} if after else {})},
            )
            users = response.get("users")
            if not isinstance(users, list):
                raise HTTPException(502, "Discord returned an invalid signup list")
            if not users:
                break
            try:
                for user in users:
                    if not user.get("bot"):
                        player_id = str(user["id"])
                        players[player_id] = {
                            "id": player_id,
                            "name": user.get("global_name") or user["username"],
                        }
                cursor = max(int(user["id"]) for user in users)
            except (KeyError, ValueError, TypeError):
                raise HTTPException(
                    502, "Discord returned invalid voter data"
                ) from None
            if cursor <= after:
                raise HTTPException(502, "Discord signup pagination did not advance")
            after = cursor
            if len(users) < 100:
                break
        return sorted(players.values(), key=lambda player: player["name"].casefold())

    def delete_poll(self, message_id: str) -> None:
        self.bot(
            "DELETE",
            f"/channels/{self.settings.discord_channel_id}/messages/{message_id}",
        )

    def manager_context(
        self, user_id: str, guild_id: str
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        guild = self.bot("GET", f"/guilds/{guild_id}")
        member = self.bot("GET", f"/guilds/{guild_id}/members/{user_id}")
        roles = self.bot_items(f"/guilds/{guild_id}/roles")
        base = guild_permissions(guild_id, member, roles)
        if str(guild.get("owner_id")) != user_id and not base & (8 | 32):
            raise HTTPException(
                403, "You need Manage Server permission to configure this server."
            )
        return guild, member, roles

    def destination_channels(
        self, user_id: str, guild_id: str
    ) -> tuple[str, list[dict[str, str]]]:
        guild, member, roles = self.manager_context(user_id, guild_id)
        bot = self.bot("GET", "/users/@me")
        bot_member = self.bot("GET", f"/guilds/{guild_id}/members/{bot['id']}")
        channels = self.bot_items(f"/guilds/{guild_id}/channels")
        result = []
        required = (1 << 10) | (1 << 11) | (1 << 16) | (1 << 49)
        for channel in channels:
            if channel.get("type") != 0:
                continue
            user_bits = channel_permissions(guild, member, roles, channel, user_id)
            bot_bits = channel_permissions(
                guild, bot_member, roles, channel, str(bot["id"])
            )
            if user_bits & (1 << 10) and bot_bits & required == required:
                result.append({"id": str(channel["id"]), "name": str(channel["name"])})
        return str(guild["name"]), sorted(
            result, key=lambda row: row["name"].casefold()
        )

    def authorize_destination(self, user_id: str) -> None:
        guild, member, roles = self.manager_context(
            user_id, self.settings.discord_guild_id
        )
        channel = self.bot("GET", f"/channels/{self.settings.discord_channel_id}")
        if str(
            channel.get("guild_id")
        ) != self.settings.discord_guild_id or not channel_permissions(
            guild, member, roles, channel, user_id
        ) & (1 << 10):
            raise HTTPException(
                403, "You no longer have access to the configured channel."
            )


def guild_permissions(
    guild_id: str, member: dict[str, Any], roles: list[dict[str, Any]]
) -> int:
    ids = {guild_id, *map(str, member.get("roles", []))}
    bits = 0
    for role in roles:
        if str(role["id"]) in ids:
            bits |= int(role["permissions"])
    return bits


def channel_permissions(
    guild: dict[str, Any],
    member: dict[str, Any],
    roles: list[dict[str, Any]],
    channel: dict[str, Any],
    user_id: str,
) -> int:
    bits = guild_permissions(str(guild["id"]), member, roles)
    if str(guild.get("owner_id")) == user_id or bits & 8:
        return (1 << 64) - 1
    overwrites = channel.get("permission_overwrites", [])
    for overwrite in overwrites:
        if str(overwrite["id"]) == str(guild["id"]):
            bits = (bits & ~int(overwrite["deny"])) | int(overwrite["allow"])
    denied = allowed = 0
    for overwrite in overwrites:
        if overwrite.get("type") == 0 and str(overwrite["id"]) in set(
            map(str, member.get("roles", []))
        ):
            denied |= int(overwrite["deny"])
            allowed |= int(overwrite["allow"])
    bits = (bits & ~denied) | allowed
    for overwrite in overwrites:
        if overwrite.get("type") == 1 and str(overwrite["id"]) == user_id:
            bits = (bits & ~int(overwrite["deny"])) | int(overwrite["allow"])
    return bits
