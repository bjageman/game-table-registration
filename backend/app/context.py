"""Application dependencies and shared request authorization."""

import re
import secrets
import time
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm import object_session

from app.assignment_preferences import scope_key
from app.config import Settings
from app.discord_api import DiscordAPI
from app.models import (
    Event,
    EventPlayerSetting,
    Organization,
    OrganizationMember,
    OrganizationSelection,
    PlayerProfile,
    Session,
    UserSettings,
)
from app.player_profiles import PlayerScope
from app.player_profiles import for_event as player_scope_for_event
from app.security import digest


@dataclass
class ApplicationContext:
    app: FastAPI
    config: Settings
    engine: Engine

    def cookie(self, response: Response, name: str, value: str, age: int) -> None:
        response.set_cookie(
            name,
            value,
            max_age=age,
            httponly=True,
            secure=self.config.public_url.startswith("https://"),
            samesite="lax",
            path="/api",
        )

    def client_for(self, target: Settings) -> DiscordAPI:
        if (target.discord_guild_id, target.discord_channel_id) == (
            self.config.discord_guild_id,
            self.config.discord_channel_id,
        ):
            client: DiscordAPI = self.app.state.discord
            return client
        scoped: DiscordAPI = self.app.state.discord.at(
            target.discord_guild_id, target.discord_channel_id
        )
        return scoped

    def destination(self, request: Request) -> Settings:
        target: Settings = request.state.destination
        return target

    def scoped_discord(self, request: Request) -> DiscordAPI:
        client: DiscordAPI = request.state.discord
        return client

    def player_scope(self, request: Request) -> PlayerScope:
        return PlayerScope(
            scope_key(request.state.organization_id, request.state.user_id),
            self.destination(request).discord_guild_id,
        )

    def event_scope(self, request: Request) -> tuple[Any, ...]:
        target = self.destination(request)
        organization_id = request.state.organization_id
        return (
            Event.organization_id == organization_id
            if organization_id
            else (
                Event.organization_id.is_(None)
                & (Event.created_by == request.state.user_id)
            ),
            Event.guild_id == target.discord_guild_id,
            func.coalesce(Event.channel_id, self.config.discord_channel_id)
            == target.discord_channel_id,
        )

    def matches_destination(self, event: Event, request: Request) -> bool:
        target = self.destination(request)
        return (
            (
                event.organization_id == request.state.organization_id
                if request.state.organization_id
                else event.organization_id is None
                and event.created_by == request.state.user_id
            )
            and event.guild_id == target.discord_guild_id
            and (event.channel_id or self.config.discord_channel_id)
            == target.discord_channel_id
        )

    def legacy_access(self, user_id: str) -> bool:
        if not self.config.discord_guild_id or not self.config.discord_channel_id:
            return False
        try:
            self.app.state.discord.authorize(user_id)
            return True
        except HTTPException:
            return False

    def authenticated(
        self,
        request: Request,
        mutation: bool = False,
        require_destination: bool = True,
        require_channel: bool = True,
    ) -> Session:
        with DBSession(self.engine) as db:
            session = db.get(Session, digest(request.cookies.get("session", "")))
            if not session or session.expires <= time.time():
                raise HTTPException(401, "Sign in with Discord to continue.")
            if mutation and (
                request.headers.get("origin") != self.config.public_url
                or not secrets.compare_digest(
                    request.headers.get("x-csrf-token", ""), session.csrf
                )
            ):
                raise HTTPException(403, "Invalid request. Refresh and try again.")
            request.state.user_id = session.user_id
            selection = db.get(OrganizationSelection, session.user_id)
            organization = (
                db.get(Organization, selection.organization_id) if selection else None
            )
            member = (
                db.get(OrganizationMember, (organization.id, session.user_id))
                if organization
                else None
            )
            if organization and not member:
                organization = None
            request.state.organization_id = organization.id if organization else None
            request.state.organization_role = (
                member.role if organization and member else None
            )
            if not require_destination:
                return session
            if mutation and organization and member and member.role == "user":
                raise HTTPException(
                    403, "This organization is read-only for your account."
                )
            saved = db.get(UserSettings, session.user_id)
            if (organization and not organization.channel_id) or (
                saved and saved.disconnected and not organization
            ):
                raise HTTPException(
                    409, "Choose a server and channel in Settings first."
                )
            target = (
                self.config.model_copy(
                    update={
                        "discord_guild_id": organization.guild_id,
                        "discord_channel_id": organization.channel_id,
                    }
                )
                if organization
                else self.config.model_copy(
                    update={
                        "discord_guild_id": saved.guild_id,
                        "discord_channel_id": saved.channel_id,
                    }
                )
                if saved
                else self.config
            )
            if not target.discord_guild_id or (
                require_channel and not target.discord_channel_id
            ):
                raise HTTPException(
                    409, "Choose a server and channel in Settings first."
                )
            discord = self.client_for(target)
            if organization:
                pass
            elif saved and not require_channel:
                discord.manager_context(session.user_id, target.discord_guild_id)
            elif saved:
                discord.authorize_destination(session.user_id)
            else:
                discord.authorize(session.user_id)
            request.state.destination = target
            request.state.discord = discord
            return session

    def serialize(self, event: Event) -> dict[str, Any]:
        warnings: list[str] = []
        if event.status in ("review", "assigned") and event.close_pairs:
            from app.models import LotteryRun
            from app.withdrawals import current_result

            db = object_session(event)
            run = db.get(LotteryRun, event.id) if db else None
            if db and run and run.result.get("pairing_conflicts"):
                warnings = current_result(db, run).get("pairing_warnings", [])
        return {
            "id": event.id,
            "title": event.title,
            "description": event.description,
            "location": event.location,
            "starts_at": event.starts_at,
            "duration_hours": event.duration_hours,
            "tables": event.tables,
            "status": event.status,
            "signup_mode": event.signup_mode,
            "closes_at": event.closes_at
            if event.closes_at is not None
            else event.scheduled_publish_at + event.duration_hours * 3600
            if event.series_id and event.scheduled_publish_at is not None
            else None,
            "published_at": event.published_at,
            "series_id": event.series_id,
            "scheduled_publish_at": event.scheduled_publish_at,
            "archived_at": event.archived_at,
            "signup_deleted_at": event.signup_deleted_at,
            "close_error": event.close_error or event.reaction_error,
            "pairing_warnings": warnings,
            "is_test": bool(event.test_signups),
            "test_generation": event.test_signups.get("generation")
            if event.test_signups
            else None,
            "test_user_count": len(event.test_signups["players"])
            if event.test_signups
            else 0,
            "discord_url": (
                f"https://discord.com/channels/{event.guild_id}/"
                f"{event.channel_id or self.config.discord_channel_id}/"
                f"{event.message_id}"
            )
            if event.message_id and not event.signup_deleted_at
            else None,
        }

    def discord_name(self, player_id: str) -> str:
        discord: DiscordAPI = self.app.state.discord
        user = discord.bot("GET", f"/users/{player_id}")
        name = user.get("global_name") or user.get("username")
        if not isinstance(name, str) or not name:
            raise HTTPException(502, "Discord returned an invalid user profile")
        return name

    def player_data(
        self,
        player_id: str,
        profile: PlayerProfile | None,
        signup_name: str | None = None,
    ) -> dict[str, Any]:
        return {
            "discord_id": player_id,
            "discord_name": profile.discord_name
            if profile
            else signup_name or self.discord_name(player_id),
            "real_name": profile.real_name if profile else "",
            "weighting": profile.weighting if profile else 5.0,
            "is_test": profile.is_test if profile else False,
            "guaranteed_seat": profile.guaranteed_seat if profile else False,
            "partner_id": profile.partner_id if profile else None,
        }

    def valid_player_id(self, player_id: str) -> None:
        if re.fullmatch(r"test-[a-f0-9]{24}", player_id):
            return
        if not player_id.isascii() or not player_id.isdecimal() or len(player_id) > 32:
            raise HTTPException(422, "Invalid Discord user ID")

    def list_names(
        self, rows: list[dict[str, Any]], event_id: str
    ) -> list[dict[str, Any]]:
        # Decorate copies for the app; saved results keep Discord names.
        with DBSession(self.engine) as db:
            event = db.get(Event, event_id)
            if event is None:
                raise ValueError("An event is required to resolve scoped player names")
            scope = player_scope_for_event(event)
            profiles = {
                profile.discord_id: profile
                for profile in db.scalars(
                    select(PlayerProfile).where(
                        *scope.filters(),
                    )
                )
            }
            settings = (
                {
                    setting.discord_id: setting
                    for setting in db.scalars(
                        select(EventPlayerSetting).where(
                            EventPlayerSetting.event_id == event_id
                        )
                    )
                }
                if event_id
                else {}
            )

        def decorate(player: dict[str, Any]) -> dict[str, Any]:
            profile = profiles.get(player["id"])
            setting = settings.get(player["id"])
            result = {**player}
            if profile and profile.real_name:
                result["display_name"] = profile.real_name
            if event_id:
                result.update(
                    weighting=(
                        setting.weighting
                        if setting and setting.weighting is not None
                        else profile.weighting
                        if profile
                        else 5.0
                    ),
                    guaranteed_table=setting.guaranteed_table if setting else None,
                    guaranteed_seat=profile.guaranteed_seat if profile else False,
                )
            return result

        return [
            {
                **row,
                **{
                    key: [decorate(player) for player in row[key]]
                    for key in ("players", "waitlist")
                    if key in row
                },
            }
            for row in rows
        ]

    def client_for_destination(self, guild: str, channel: str) -> DiscordAPI:
        return self.client_for(
            self.config.model_copy(
                update={
                    "discord_guild_id": guild,
                    "discord_channel_id": channel,
                }
            )
        )

    def scoped_event(self, db: DBSession, event_id: str, request: Request) -> Event:
        event = db.get(Event, event_id)
        if event is None or not self.matches_destination(event, request):
            raise HTTPException(404, "Event not found")
        return event
