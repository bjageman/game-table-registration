"""Players API routes."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.context import ApplicationContext
from app.models import (
    Event,
    LotteryRun,
    PlayerProfile,
    TableSignup,
)
from app.schemas import (
    PlayerProfileInput,
)


def register(context: ApplicationContext) -> None:
    router = APIRouter()
    authenticated = context.authenticated
    destination = context.destination
    discord_name = context.discord_name
    engine = context.engine
    player_data = context.player_data
    valid_player_id = context.valid_player_id

    @router.get("/api/players")
    def players(request: Request) -> list[dict[str, Any]]:
        authenticated(request)
        guild_id = destination(request).discord_guild_id
        found: dict[str, dict[str, Any]] = {}
        with DBSession(engine) as db:
            for profile in db.scalars(
                select(PlayerProfile).where(PlayerProfile.guild_id == guild_id)
            ):
                found[profile.discord_id] = player_data(profile.discord_id, profile)
            for player_id, name in db.execute(
                select(TableSignup.discord_id, TableSignup.discord_name)
                .join(Event, Event.id == TableSignup.event_id)
                .where(Event.guild_id == guild_id)
            ):
                found.setdefault(player_id, player_data(player_id, None, name))
            for snapshot in db.scalars(
                select(LotteryRun.snapshot)
                .join(Event, Event.id == LotteryRun.event_id)
                .where(Event.guild_id == guild_id)
            ):
                for player in snapshot.get("players", []):
                    player_id = str(player.get("id", ""))
                    name = player.get("name")
                    if player_id and isinstance(name, str):
                        found.setdefault(player_id, player_data(player_id, None, name))
                        if player.get("is_test"):
                            found[player_id]["is_test"] = True
        return sorted(
            found.values(),
            key=lambda player: (
                (player["real_name"] or player["discord_name"]).casefold(),
                player["discord_id"],
            ),
        )

    @router.get("/api/players/{player_id}")
    def player_profile(
        player_id: str, request: Request, signup_name: str | None = None
    ) -> dict[str, Any]:
        authenticated(request)
        valid_player_id(player_id)
        with DBSession(engine) as db:
            profile = db.get(
                PlayerProfile, (destination(request).discord_guild_id, player_id)
            )
            if player_id.startswith("test-") and (
                profile is None or not profile.is_test
            ):
                raise HTTPException(404, "Test player not found")
            return player_data(player_id, profile, signup_name)

    @router.put("/api/players/{player_id}")
    def save_player_profile(
        player_id: str, body: PlayerProfileInput, request: Request
    ) -> dict[str, Any]:
        authenticated(request, True)
        valid_player_id(player_id)
        if all(
            value is None
            for value in (body.real_name, body.guaranteed_seat, body.weighting)
        ):
            raise HTTPException(422, "Specify a profile setting to update")
        with DBSession(engine) as db:
            profile = db.get(
                PlayerProfile, (destination(request).discord_guild_id, player_id)
            )
            if player_id.startswith("test-") and (
                profile is None or not profile.is_test
            ):
                raise HTTPException(404, "Test player not found")
            if profile is None:
                profile = PlayerProfile(
                    guild_id=destination(request).discord_guild_id,
                    discord_id=player_id,
                    discord_name=discord_name(player_id),
                    real_name=body.real_name or "",
                    weighting=body.weighting if body.weighting is not None else 5.0,
                )
                db.add(profile)
            else:
                if body.real_name is not None:
                    profile.real_name = body.real_name
                if body.weighting is not None:
                    profile.weighting = body.weighting

            def apply_guarantee(profile: PlayerProfile) -> None:
                if body.guaranteed_seat is not None:
                    profile.guaranteed_seat = body.guaranteed_seat

            apply_guarantee(profile)
            try:
                db.commit()
            except IntegrityError:
                # Another moderator may have created this profile concurrently.
                db.rollback()
                profile = db.get(
                    PlayerProfile, (destination(request).discord_guild_id, player_id)
                )
                if profile is None:
                    raise
                if body.real_name is not None:
                    profile.real_name = body.real_name
                if body.weighting is not None:
                    profile.weighting = body.weighting
                apply_guarantee(profile)
                db.commit()
            return player_data(player_id, profile)

    context.app.include_router(router)
