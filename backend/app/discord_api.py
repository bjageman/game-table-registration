from typing import Any

import httpx
from fastapi import HTTPException

from app.config import Settings


class DiscordAPI:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
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
            return dict(response.json())
        except (httpx.HTTPError, ValueError):
            raise HTTPException(
                502, "Discord request failed. Please try again."
            ) from None

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
        return self.request(
            "GET",
            "/users/@me",
            headers={"Authorization": f"Bearer {token['access_token']}"},
        )

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
