"""Player profiles and reciprocal pairing within the selected organization."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.context import ApplicationContext
from app.models import Event, LotteryRun, PlayerPreference, PlayerProfile, TableSignup
from app.schemas import PlayerPreferencesInput, PlayerProfileInput


def register(context: ApplicationContext) -> None:
    router = APIRouter()
    engine = context.engine

    def preference_data(
        profiles: dict[str, PlayerProfile], ids: list[str]
    ) -> list[dict[str, str]]:
        return sorted(
            [
                {
                    "id": pid,
                    "name": profiles[pid].real_name or profiles[pid].discord_name,
                }
                for pid in ids
                if pid in profiles
            ],
            key=lambda player: (player["name"].casefold(), player["id"]),
        )

    def profile_data(
        db: DBSession,
        request: Request,
        player_id: str,
        profile: PlayerProfile | None,
        name: str | None = None,
    ) -> dict[str, Any]:
        result = context.player_data(player_id, profile, name)
        scope = context.player_scope(request)
        profiles = {
            p.discord_id: p
            for p in db.scalars(select(PlayerProfile).where(*scope.filters()))
        }
        result["paired_preferences"] = preference_data(
            profiles, scope.preferences(db).get(player_id, [])
        )
        return result

    def known_players(db: DBSession, request: Request) -> dict[str, dict[str, Any]]:
        scope = context.player_scope(request)
        event_filters = (
            Event.guild_id == scope.guild_id,
            Event.organization_id == request.state.organization_id
            if request.state.organization_id
            else Event.organization_id.is_(None)
            & (Event.created_by == request.state.user_id),
        )
        profiles = {
            p.discord_id: p
            for p in db.scalars(select(PlayerProfile).where(*scope.filters()))
        }
        preferences = scope.preferences(db)
        found = {
            pid: {
                **context.player_data(pid, p),
                "paired_preferences": preference_data(
                    profiles, preferences.get(pid, [])
                ),
            }
            for pid, p in profiles.items()
        }
        for player_id, name in db.execute(
            select(TableSignup.discord_id, TableSignup.discord_name)
            .join(Event, Event.id == TableSignup.event_id)
            .where(*event_filters)
        ):
            found.setdefault(player_id, context.player_data(player_id, None, name))
        for snapshot in db.scalars(
            select(LotteryRun.snapshot)
            .join(Event, Event.id == LotteryRun.event_id)
            .where(*event_filters)
        ):
            for player in snapshot.get("players", []):
                player_id = str(player.get("id", ""))
                name = player.get("name")
                if player_id and isinstance(name, str):
                    found.setdefault(
                        player_id, context.player_data(player_id, None, name)
                    )
                    if player.get("is_test"):
                        found[player_id]["is_test"] = True
        for player in found.values():
            player.setdefault("paired_preferences", [])
        return found

    @router.get("/api/players")
    def players(request: Request) -> list[dict[str, Any]]:
        context.authenticated(request)
        with DBSession(engine) as db:
            found = known_players(db, request)
            return sorted(
                found.values(),
                key=lambda p: (
                    (p["real_name"] or p["discord_name"]).casefold(),
                    p["discord_id"],
                ),
            )

    @router.get("/api/players/{player_id}")
    def player_profile(
        player_id: str, request: Request, signup_name: str | None = None
    ) -> dict[str, Any]:
        context.authenticated(request)
        context.valid_player_id(player_id)
        with DBSession(engine) as db:
            profile = context.player_scope(request).get(db, player_id)
            if player_id.startswith("test-") and (
                profile is None or not profile.is_test
            ):
                raise HTTPException(404, "Test player not found")
            return profile_data(db, request, player_id, profile, signup_name)

    @router.put("/api/players/{player_id}")
    def save_player_profile(
        player_id: str, body: PlayerProfileInput, request: Request
    ) -> dict[str, Any]:
        context.authenticated(request, True)
        context.valid_player_id(player_id)
        changes = body.model_dump(exclude_none=True)
        if not changes:
            raise HTTPException(422, "Specify a profile setting to update")
        scope = context.player_scope(request)
        with DBSession(engine) as db:
            # Serialize profile creation with notification opt-outs and pairing edits.
            scope.lock(db)
            profile = scope.get(db, player_id)
            if player_id.startswith("test-") and (
                profile is None or not profile.is_test
            ):
                raise HTTPException(404, "Test player not found")
            if profile is None:
                profile = scope.create(
                    player_id, discord_name=context.discord_name(player_id)
                )
                db.add(profile)
            for key, value in changes.items():
                setattr(profile, key, value)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                profile = scope.get(db, player_id)
                if profile is None:
                    raise
                for key, value in changes.items():
                    setattr(profile, key, value)
                db.commit()
            return profile_data(db, request, player_id, profile)

    @router.put("/api/players/{player_id}/preferences")
    def save_preferences(
        player_id: str, body: PlayerPreferencesInput, request: Request
    ) -> dict[str, Any]:
        context.authenticated(request, True)
        context.valid_player_id(player_id)
        targets = set(body.player_ids)
        for pid in targets:
            context.valid_player_id(pid)
        if player_id in targets:
            raise HTTPException(422, "A player cannot prefer themselves")
        scope = context.player_scope(request)
        with DBSession(engine) as db:
            scope.lock(db)
            known = known_players(db, request)
            for pid in targets | {player_id}:
                if pid not in known:
                    raise HTTPException(404, "Player not found in this organization")
                if scope.get(db, pid) is None:
                    data = known[pid]
                    db.add(
                        scope.create(
                            pid,
                            discord_name=data["discord_name"],
                            is_test=data["is_test"],
                        )
                    )
            edges = list(
                db.scalars(
                    select(PlayerPreference).where(
                        PlayerPreference.scope_key == scope.key,
                        PlayerPreference.guild_id == scope.guild_id,
                        (PlayerPreference.player_id == player_id)
                        | (PlayerPreference.preferred_id == player_id),
                    )
                )
            )
            existing = set()
            for edge in edges:
                other = (
                    edge.preferred_id if edge.player_id == player_id else edge.player_id
                )
                existing.add(other)
                if other not in targets:
                    db.delete(edge)
            for target in sorted(targets - existing):
                first, second = sorted((player_id, target))
                db.add(
                    PlayerPreference(
                        scope_key=scope.key,
                        guild_id=scope.guild_id,
                        player_id=first,
                        preferred_id=second,
                    )
                )
            db.commit()
            return {
                "profile": profile_data(
                    db, request, player_id, scope.get(db, player_id)
                )
            }

    context.app.include_router(router)
