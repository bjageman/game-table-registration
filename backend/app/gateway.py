"""Receive table signup interactions over an outbound Discord connection."""

import asyncio
import logging
import time
from typing import Any

import discord
from sqlalchemy import Engine

from app import reactions
from app.config import Settings
from app.discord_api import DiscordAPI
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
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_reactions = True
        super().__init__(intents=intents, max_messages=None)
        self.engine = engine
        self.config = config
        self.reaction_lock = asyncio.Lock()
        self.reaction_task: asyncio.Task[None] | None = None

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
        await asyncio.to_thread(reactions.mark_gap, self.engine)

    async def on_ready(self) -> None:
        logger.info("Discord signup Gateway connected")
        await self.sync_reactions()
        if self.reaction_task is None or self.reaction_task.done():
            self.reaction_task = asyncio.create_task(self.watch_reactions())

    async def on_resumed(self) -> None:
        await self.sync_reactions()

    async def on_disconnect(self) -> None:
        async with self.reaction_lock:
            await asyncio.to_thread(reactions.mark_gap, self.engine)

    async def sync_reactions(self) -> None:
        async with self.reaction_lock:
            for event in await asyncio.to_thread(reactions.pending, self.engine):
                if event["sync"]:
                    if not event["deadline"] or time.time() >= event["deadline"]:
                        continue
                    try:
                        started = time.time()
                        api = DiscordAPI(self.config).at(
                            event["guild"], event["channel"]
                        )
                        players = await asyncio.to_thread(
                            api.reaction_players, event["message"], event["tables"]
                        )
                        await asyncio.to_thread(
                            reactions.replace,
                            self.engine,
                            event["id"],
                            players,
                            started,
                        )
                    except Exception:
                        logger.exception("Could not synchronize reaction signups")
                elif self.is_ready():
                    await asyncio.to_thread(
                        reactions.checkpoint, self.engine, event["id"]
                    )

    async def watch_reactions(self) -> None:
        while True:
            await asyncio.sleep(5)
            if self.is_ready():
                try:
                    await self.sync_reactions()
                except Exception:
                    logger.exception("Reaction signup synchronization failed")

    async def reaction_change(
        self, event: discord.RawReactionActionEvent, added: bool
    ) -> None:
        observed = time.time()
        if event.guild_id is None or event.emoji.id is not None:
            return
        if event.emoji.name not in reactions.EMOJIS:
            return
        if self.user and event.user_id == self.user.id:
            return
        if event.type != discord.ReactionType.normal:
            return
        async with self.reaction_lock:
            event_id = await asyncio.to_thread(
                reactions.event_for,
                self.engine,
                str(event.guild_id),
                str(event.channel_id),
                str(event.message_id),
            )
            if event_id is None:
                return
            try:
                name = ""
                if added:
                    user = event.member or await self.fetch_user(event.user_id)
                    if user.bot:
                        return
                    name = user.display_name
                await asyncio.to_thread(
                    reactions.change,
                    self.engine,
                    event_id,
                    event.emoji.name,
                    str(event.user_id),
                    name,
                    added,
                    observed,
                )
            except Exception:
                await asyncio.to_thread(reactions.mark_gap, self.engine)
                logger.exception("Could not record a table reaction")

    async def on_raw_reaction_add(self, event: discord.RawReactionActionEvent) -> None:
        await self.reaction_change(event, True)

    async def on_raw_reaction_remove(
        self, event: discord.RawReactionActionEvent
    ) -> None:
        await self.reaction_change(event, False)

    async def clear_reactions(
        self, guild: int | None, channel: int, message: int, emoji: str | None
    ) -> None:
        observed = time.time()
        async with self.reaction_lock:
            event_id = await asyncio.to_thread(
                reactions.event_for, self.engine, str(guild), str(channel), str(message)
            )
            if event_id:
                await asyncio.to_thread(
                    reactions.change,
                    self.engine,
                    event_id,
                    emoji,
                    None,
                    "",
                    False,
                    observed,
                )

    async def on_raw_reaction_clear(self, event: discord.RawReactionClearEvent) -> None:
        await self.clear_reactions(
            event.guild_id, event.channel_id, event.message_id, None
        )

    async def on_raw_reaction_clear_emoji(
        self, event: discord.RawReactionClearEmojiEvent
    ) -> None:
        if event.emoji.id is None and event.emoji.name in reactions.EMOJIS:
            await self.clear_reactions(
                event.guild_id, event.channel_id, event.message_id, event.emoji.name
            )

    async def close(self) -> None:
        if self.reaction_task:
            self.reaction_task.cancel()
            await asyncio.gather(self.reaction_task, return_exceptions=True)
            self.reaction_task = None
        await super().close()

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
