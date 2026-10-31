"""Guild-only player controls; no message-content intent required."""

import asyncio

import discord
from discord import app_commands
from fastapi import HTTPException
from sqlalchemy import create_engine

from app.config import Settings
from app.live_votes import record_vote
from app.players import player_status, withdraw


class TableBot(discord.Client):
    def __init__(self, config: Settings) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_polls = True
        super().__init__(intents=intents)
        self.config = config
        self.engine = create_engine(config.database_url, pool_pre_ping=True)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        guild = discord.Object(id=int(self.config.discord_guild_id))

        @self.tree.command(
            name="signup_status",
            description="Check your signup or withdrawal for an event",
            guild=guild,
        )
        async def status(
            interaction: discord.Interaction[TableBot], event_id: str
        ) -> None:
            await interaction.response.defer(ephemeral=True)
            if (
                str(interaction.guild_id) != self.config.discord_guild_id
                or interaction.user.bot
            ):
                await interaction.followup.send(
                    "Use this command in the configured server.", ephemeral=True
                )
                return
            try:
                result = await asyncio.to_thread(
                    player_status,
                    self.engine,
                    self.config.discord_guild_id,
                    str(interaction.user.id),
                    event_id,
                )
                details = (
                    "Withdrawn; further poll votes will not re-enter this event."
                    if result["withdrawn"]
                    else (
                        "Selected tables: " + (", ".join(result["tables"]) or "none")
                        if result["reconciled"]
                        else "Final votes are not reconciled yet; "
                        "use the event poll to review choices."
                    )
                )
                content = f"{result['title']} — {result['status']}. {details}"
                await interaction.followup.send(
                    discord.utils.escape_mentions(content),
                    ephemeral=True,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except HTTPException as failure:
                await interaction.followup.send(str(failure.detail), ephemeral=True)

        @self.tree.command(
            name="withdraw_signup",
            description="Withdraw your lottery entry for an event",
            guild=guild,
        )
        async def remove(
            interaction: discord.Interaction[TableBot], event_id: str
        ) -> None:
            await interaction.response.defer(ephemeral=True)
            if (
                str(interaction.guild_id) != self.config.discord_guild_id
                or interaction.user.bot
            ):
                await interaction.followup.send(
                    "Use this command in the configured server.", ephemeral=True
                )
                return
            try:
                await asyncio.to_thread(
                    withdraw,
                    self.engine,
                    self.config.discord_guild_id,
                    str(interaction.user.id),
                    event_id,
                )
                await interaction.followup.send(
                    "Your entry is withdrawn. "
                    "Further poll votes will not re-enter this event.",
                    ephemeral=True,
                )
            except HTTPException as failure:
                await interaction.followup.send(str(failure.detail), ephemeral=True)

        await self.tree.sync(guild=guild)

    async def on_raw_poll_vote_add(
        self, payload: discord.RawPollVoteActionEvent
    ) -> None:
        await self.track_vote(payload, True)

    async def on_raw_poll_vote_remove(
        self, payload: discord.RawPollVoteActionEvent
    ) -> None:
        await self.track_vote(payload, False)

    async def track_vote(
        self, payload: discord.RawPollVoteActionEvent, added: bool
    ) -> None:
        if (
            str(payload.guild_id) != self.config.discord_guild_id
            or str(payload.channel_id) != self.config.discord_channel_id
        ):
            return
        await asyncio.to_thread(
            record_vote,
            self.engine,
            self.config.discord_guild_id,
            str(payload.message_id),
            str(payload.user_id),
            payload.answer_id,
            added,
        )

    async def close(self) -> None:
        self.engine.dispose()
        await super().close()


def main() -> None:
    config = Settings()
    if not config.configured:
        raise RuntimeError(
            "Configure Discord credentials before starting player commands"
        )
    TableBot(config).run(config.discord_bot_token)


if __name__ == "__main__":
    main()
