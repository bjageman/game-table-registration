"""Receive table signup interactions over an outbound Discord connection."""

import asyncio
import logging
from typing import Any

import discord
from sqlalchemy import Engine

from app.config import Settings
from app.signups import handle

logger = logging.getLogger("uvicorn.error")


def payload(interaction: discord.Interaction[discord.Client]) -> dict[str, Any]:
    user = interaction.user
    message = interaction.message
    return {
        "id": str(interaction.id),
        "application_id": str(interaction.application_id),
        "type": interaction.type.value,
        "guild_id": str(interaction.guild_id),
        "channel_id": str(interaction.channel_id),
        "data": interaction.data,
        "member": {
            "nick": user.nick if isinstance(user, discord.Member) else None,
            "user": {
                "id": str(user.id),
                "username": user.name,
                "global_name": user.global_name,
                "bot": user.bot,
            },
        },
        "message": {
            "id": str(message.id),
            "flags": message.flags.value,
            "author": {"id": str(message.author.id)},
        }
        if message
        else {},
    }


def view_for(data: dict[str, Any]) -> discord.ui.View | None:
    if not data.get("components"):
        return None
    # on_interaction routes all signup custom IDs, including messages created
    # before a restart. These views do not need per-message callback registration.
    view = discord.ui.View(timeout=900)
    for row, group in enumerate(data["components"]):
        for component in group["components"]:
            if component["type"] == 3:
                view.add_item(
                    discord.ui.Select(
                        custom_id=component["custom_id"],
                        placeholder=component["placeholder"],
                        min_values=component["min_values"],
                        max_values=component["max_values"],
                        options=[
                            discord.SelectOption(**option)
                            for option in component["options"]
                        ],
                        row=row,
                    )
                )
            elif component["type"] == 2:
                view.add_item(
                    discord.ui.Button(
                        custom_id=component["custom_id"],
                        label=component["label"],
                        style=discord.ButtonStyle(component["style"]),
                        disabled=component.get("disabled", False),
                        row=row,
                    )
                )
    return view


class SignupGateway(discord.Client):
    def __init__(self, engine: Engine, config: Settings) -> None:
        # Component interactions require no privileged intents or message cache.
        super().__init__(intents=discord.Intents.none(), max_messages=None)
        self.engine = engine
        self.config = config

    async def setup_hook(self) -> None:
        application = await self.application_info()
        if str(application.id) != self.config.discord_client_id:
            raise RuntimeError(
                "Bot token and Discord client ID refer to different apps"
            )
        if application.interactions_endpoint_url:
            raise RuntimeError(
                "Clear the Interactions Endpoint URL in Discord Developer Portal "
                "to receive signup interactions through Gateway"
            )

    async def on_ready(self) -> None:
        logger.info("Discord signup Gateway connected")

    async def on_interaction(
        self, interaction: discord.Interaction[discord.Client]
    ) -> None:
        data: dict[str, Any] = dict(interaction.data or {})
        custom_id = data.get("custom_id")
        if (
            interaction.type != discord.InteractionType.component
            or not isinstance(custom_id, str)
            or not custom_id.startswith("signup:")
        ):
            return
        # Acknowledge before doing database work to meet Discord's three-second
        # deadline. Only update an existing message when it is a private app menu.
        message = interaction.message
        private_menu = bool(
            message
            and message.flags.ephemeral
            and str(message.author.id) == self.config.discord_client_id
        )
        try:
            await interaction.response.defer(ephemeral=True, thinking=not private_menu)
        except discord.HTTPException:
            # Never mutate signups if Discord did not accept the acknowledgement.
            logger.warning("Discord could not acknowledge a signup interaction")
            return
        try:
            result = await asyncio.to_thread(
                handle, self.engine, self.config, payload(interaction)
            )
            response = result["data"]
        except Exception:
            logger.exception("Signup interaction could not be processed")
            response = {
                "content": "Could not save your signup. Reopen My signup "
                "to check your choices and try again."
            }
        try:
            await interaction.edit_original_response(
                content=response["content"],
                view=view_for(response),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            logger.warning(
                "Could not display signup confirmation; saved choices remain available"
            )

    async def run_listener(self) -> None:
        try:
            await self.start(self.config.discord_bot_token, reconnect=True)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # Config errors are actionable; avoid logging tokens or raw payloads.
            logger.error("Discord signup Gateway stopped: %s", str(error))
        finally:
            await self.close()
