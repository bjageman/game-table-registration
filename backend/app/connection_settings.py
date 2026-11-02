from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import Engine
from sqlalchemy.orm import Session as DBSession

from app.config import Settings
from app.discord_api import DiscordAPI
from app.models import Session, UserSettings

# Custom signups need View Channel, Send Messages, and Read Message History.
SIGNUP_PERMISSIONS = (1 << 10) | (1 << 11) | (1 << 16) | (1 << 6)
POLL_PERMISSIONS = SIGNUP_PERMISSIONS | (1 << 49)


class DestinationInput(BaseModel):
    model_config = {"extra": "forbid"}
    guild_id: str = Field(pattern=r"^[0-9]{1,32}$")
    channel_id: str = Field(pattern=r"^[0-9]{1,32}$")


def register_settings(
    app: FastAPI,
    engine: Engine,
    config: Settings,
    authenticated: Callable[..., Session],
    legacy_access: Callable[[str], bool],
) -> None:
    @app.get("/api/settings")
    def settings(request: Request) -> dict[str, Any]:
        session = authenticated(request, require_destination=False)
        with DBSession(engine) as db:
            saved = db.get(UserSettings, session.user_id)
            selection = (
                {
                    "guild_id": saved.guild_id,
                    "guild_name": saved.guild_name,
                    "channel_id": saved.channel_id,
                    "channel_name": saved.channel_name,
                }
                if saved and not saved.disconnected
                else None
            )
        guilds = [dict(g) for g in session.guilds]
        if not saved and legacy_access(session.user_id):
            selection = {
                "guild_id": config.discord_guild_id,
                "guild_name": "Current server",
                "channel_id": config.discord_channel_id,
                "channel_name": "Current channel",
            }
        if selection and not any(g["id"] == selection["guild_id"] for g in guilds):
            guilds.append(
                {"id": selection["guild_id"], "name": selection["guild_name"]}
            )
        return {
            "selection": selection,
            "disconnected": bool(saved and saved.disconnected),
            "guilds": guilds,
            "connect_url": "/api/auth/connect",
        }

    @app.get("/api/settings/channels")
    def channels(request: Request, guild_id: str) -> dict[str, Any]:
        session = authenticated(request, require_destination=False)
        if not guild_id.isascii() or not guild_id.isdecimal() or len(guild_id) > 32:
            raise HTTPException(422, "Choose a valid server")
        discord: DiscordAPI = app.state.discord
        guild_name, rows = discord.destination_channels(session.user_id, guild_id)
        return {"guild_name": guild_name, "channels": rows}

    @app.put("/api/settings")
    def save(request: Request, body: DestinationInput) -> dict[str, str]:
        session = authenticated(request, True, require_destination=False)
        discord: DiscordAPI = app.state.discord
        guild_name, channels = discord.destination_channels(
            session.user_id, body.guild_id
        )
        channel = next((c for c in channels if c["id"] == body.channel_id), None)
        if channel is None:
            raise HTTPException(
                403,
                "Choose a text channel you can view "
                "where TableSignup can post signups.",
            )
        with DBSession(engine) as db:
            db.merge(
                UserSettings(
                    user_id=session.user_id,
                    disconnected=False,
                    guild_id=body.guild_id,
                    guild_name=guild_name,
                    channel_id=body.channel_id,
                    channel_name=channel["name"],
                )
            )
            db.commit()
        return {
            "guild_id": body.guild_id,
            "guild_name": guild_name,
            "channel_id": body.channel_id,
            "channel_name": channel["name"],
        }

    @app.delete("/api/settings", status_code=204)
    def disconnect(request: Request) -> Response:
        session = authenticated(request, True, require_destination=False)
        with DBSession(engine) as db:
            db.merge(
                UserSettings(
                    user_id=session.user_id,
                    disconnected=True,
                    guild_id="",
                    guild_name="",
                    channel_id="",
                    channel_name="",
                )
            )
            db.commit()
        return Response(status_code=204)
