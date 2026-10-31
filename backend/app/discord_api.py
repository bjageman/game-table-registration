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
            response.raise_for_status()
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
