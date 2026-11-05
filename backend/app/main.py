import asyncio
import hashlib
import logging
import os
import re
import secrets
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from threading import Event as StopEvent
from threading import Thread
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import create_engine, delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.announcements import (
    deliver_event,
    dispatch_due,
    enqueue,
    enqueue_instructions,
)
from app.announcements import (
    status as announcement_status,
)
from app.branding import load_branding
from app.closing import close_and_assign
from app.config import Settings
from app.connection_settings import (
    POLL_PERMISSIONS,
    SIGNUP_PERMISSIONS,
    register_settings,
)
from app.discord_api import DiscordAPI, DiscordRequestError
from app.event_description import POLL_DESCRIPTION, signup_description, signup_location
from app.gateway import SignupGateway
from app.models import (
    Announcement,
    Event,
    EventManagerSignup,
    EventPlayerSetting,
    EventTemplate,
    GuildSettings,
    LoginState,
    LotteryRun,
    Organization,
    OrganizationMember,
    OrganizationSelection,
    PlayerProfile,
    Session,
    SignupInteraction,
    TableSignup,
    UserIdentity,
    UserSettings,
)
from app.reactions import EMOJIS
from app.reactions import publication as reaction_publication
from app.signup_exports import event_csv, event_pdf, summary_csv
from app.signups import apply_manager_signups, table_rows
from app.test_signups import (
    add_to_rows,
)
from app.test_signups import (
    allowed as test_users_allowed,
)
from app.test_signups import (
    generate as generate_test_users,
)
from app.withdrawals import current_result, manager_add, manager_remove


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class TableInput(BaseModel):
    name: str = Field(min_length=1, max_length=35)
    capacity: int = Field(default=15, ge=1, le=999)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Table name cannot be blank")
        return value.strip()


class EventInput(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=300)
    location: str = Field(default="", max_length=200)
    starts_at: datetime
    duration_hours: int = Field(ge=1, le=768)
    tables: list[TableInput] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_event(self) -> "EventInput":
        if not self.title.strip():
            raise ValueError("Event title cannot be blank")
        if self.starts_at.tzinfo is None:
            raise ValueError("Event time must include a timezone")
        if self.starts_at.timestamp() <= time.time() + self.duration_hours * 3600:
            raise ValueError("Event must start after the signup window ends")
        if len({table.name.casefold() for table in self.tables}) != len(self.tables):
            raise ValueError("Table names must be unique")
        return self


class EventTemplateInput(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=300)
    location: str = Field(default="", max_length=200)
    duration_hours: int = Field(ge=1, le=768)
    tables: list[TableInput] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_template(self) -> "EventTemplateInput":
        if not self.title.strip():
            raise ValueError("Event title cannot be blank")
        if len({table.name.casefold() for table in self.tables}) != len(self.tables):
            raise ValueError("Table names must be unique")
        return self


class AssignmentSettingsInput(BaseModel):
    model_config = {"extra": "forbid"}
    automatic_weight_adjustment: bool


class PlayerProfileInput(BaseModel):
    model_config = {"extra": "forbid"}
    real_name: str | None = Field(default=None, max_length=100)
    guaranteed_seat: bool | None = None
    weighting: float | None = Field(default=None, ge=0.1, le=10.0, allow_inf_nan=False)

    @field_validator("real_name")
    @classmethod
    def clean_real_name(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class EventPlayerSettingInput(BaseModel):
    model_config = {"extra": "forbid"}
    weighting: float | None = Field(default=None, ge=0.1, le=10.0, allow_inf_nan=False)
    guaranteed_table: str | None = None


class ManagerSignupInput(BaseModel):
    model_config = {"extra": "forbid"}
    table: str = Field(min_length=1, max_length=35)
    name: str = Field(min_length=1, max_length=100)


class AssignedAddInput(BaseModel):
    model_config = {"extra": "forbid"}
    table: str = Field(min_length=1, max_length=35)


class OrganizationInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class OrganizationSelectionInput(BaseModel):
    organization_id: str | None = None


class OrganizationMemberInput(BaseModel):
    user_id: str
    role: str


class TestPopulationInput(BaseModel):
    players: int = Field(default=30, ge=0, le=1000)


class RetryAnnouncementInput(BaseModel):
    confirm_repost: bool = False


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    branding = load_branding(config.branding_config_file)
    if settings is None and os.environ.get("TABLESIGNUP_LOCAL_AUTO_MIGRATE") == "1":
        if not config.database_url.startswith("sqlite:"):
            raise RuntimeError("Local automatic migrations require a SQLite database")
        from alembic import command
        from alembic.config import Config

        command.upgrade(Config("alembic.ini"), "head")
    engine = create_engine(config.database_url, pool_pre_ping=True)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        stop = StopEvent()
        gateway = (
            SignupGateway(engine, config)
            if config.discord_gateway_enabled and config.configured
            else None
        )
        application.state.gateway = gateway
        gateway_task = asyncio.create_task(gateway.run_listener()) if gateway else None

        def work() -> None:
            while not stop.is_set():
                try:
                    # Close expired signups from durable event state. This also
                    # retries events left in `closing` after Discord was still
                    # finalizing a poll or reaction synchronization.
                    with DBSession(engine) as db:
                        due: list[dict[str, Any]] = [
                            {
                                "id": event.id,
                                "guild": event.guild_id,
                                "channel": event.channel_id,
                                "message": event.message_id,
                                "mode": event.signup_mode,
                                "deleted": event.signup_deleted_at,
                            }
                            for event in db.scalars(
                                select(Event)
                                .where(
                                    Event.status.in_(["open", "closing"]),
                                    Event.closes_at.is_not(None),
                                    Event.closes_at <= time.time(),
                                    Event.message_id.is_not(None),
                                    Event.channel_id.is_not(None),
                                )
                                .limit(50)
                            )
                        ]
                    for event in due:
                        target = config.model_copy(
                            update={
                                "discord_guild_id": event["guild"],
                                "discord_channel_id": event["channel"],
                            }
                        )
                        discord = client_for(target)
                        try:
                            complete = close_and_assign(
                                engine,
                                discord,
                                event["id"],
                                "system:auto",
                                event["channel"],
                            )
                            if complete and event["message"] and not event["deleted"]:
                                if event["mode"] == "custom":
                                    discord.close_signup_message(event["message"])
                                elif event["mode"] == "reactions":
                                    discord.close_reaction_message(event["message"])
                        except Exception:
                            logging.getLogger(__name__).exception(
                                "Automatic signup closing failed for event %s",
                                event["id"],
                            )
                    dispatch_due(
                        engine,
                        lambda guild, channel: client_for(
                            config.model_copy(
                                update={
                                    "discord_guild_id": guild,
                                    "discord_channel_id": channel,
                                }
                            )
                        ),
                    )
                except Exception:
                    logging.getLogger(__name__).exception(
                        "Assignment delivery worker failed"
                    )
                stop.wait(5)

        worker = Thread(target=work, daemon=True)
        if config.announcement_worker_enabled:
            worker.start()
        try:
            yield
        finally:
            stop.set()
            if gateway:
                await gateway.close()
            if gateway_task:
                gateway_task.cancel()
                await asyncio.gather(gateway_task, return_exceptions=True)
            if worker.is_alive():
                await asyncio.to_thread(worker.join, 20)

    app = FastAPI(title=branding.name, lifespan=lifespan)
    app.state.engine = engine
    app.state.discord = DiscordAPI(config)

    @app.get("/api/branding")
    def public_branding() -> dict[str, str | None]:
        return branding.model_dump()

    def cookie(response: Response, name: str, value: str, age: int) -> None:
        response.set_cookie(
            name,
            value,
            max_age=age,
            httponly=True,
            secure=config.public_url.startswith("https://"),
            samesite="lax",
            path="/api",
        )

    def client_for(target: Settings) -> DiscordAPI:
        if (target.discord_guild_id, target.discord_channel_id) == (
            config.discord_guild_id,
            config.discord_channel_id,
        ):
            client: DiscordAPI = app.state.discord
            return client
        scoped: DiscordAPI = app.state.discord.at(
            target.discord_guild_id, target.discord_channel_id
        )
        return scoped

    def destination(request: Request) -> Settings:
        target: Settings = request.state.destination
        return target

    def scoped_discord(request: Request) -> DiscordAPI:
        client: DiscordAPI = request.state.discord
        return client

    def event_scope(request: Request) -> tuple[Any, ...]:
        target = destination(request)
        organization_id = request.state.organization_id
        return (
            Event.organization_id == organization_id
            if organization_id
            else (
                Event.organization_id.is_(None)
                & (Event.created_by == request.state.user_id)
            ),
            Event.guild_id == target.discord_guild_id,
            func.coalesce(Event.channel_id, config.discord_channel_id)
            == target.discord_channel_id,
        )

    def matches_destination(event: Event, request: Request) -> bool:
        target = destination(request)
        return (
            (
                event.organization_id == request.state.organization_id
                if request.state.organization_id
                else event.organization_id is None
                and event.created_by == request.state.user_id
            )
            and event.guild_id == target.discord_guild_id
            and (event.channel_id or config.discord_channel_id)
            == target.discord_channel_id
        )

    def legacy_access(user_id: str) -> bool:
        if not config.discord_guild_id or not config.discord_channel_id:
            return False
        try:
            app.state.discord.authorize(user_id)
            return True
        except HTTPException:
            return False

    def authenticated(
        request: Request,
        mutation: bool = False,
        require_destination: bool = True,
        require_channel: bool = True,
    ) -> Session:
        with DBSession(engine) as db:
            session = db.get(Session, digest(request.cookies.get("session", "")))
            if not session or session.expires <= time.time():
                raise HTTPException(401, "Sign in with Discord to continue.")
            if mutation and (
                request.headers.get("origin") != config.public_url
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
            if saved and saved.disconnected and not organization:
                raise HTTPException(
                    409, "Choose a server and channel in Settings first."
                )
            target = (
                config.model_copy(
                    update={
                        "discord_guild_id": organization.guild_id,
                        "discord_channel_id": organization.channel_id,
                    }
                )
                if organization
                else config.model_copy(
                    update={
                        "discord_guild_id": saved.guild_id,
                        "discord_channel_id": saved.channel_id,
                    }
                )
                if saved
                else config
            )
            if not target.discord_guild_id or (
                require_channel and not target.discord_channel_id
            ):
                raise HTTPException(
                    409, "Choose a server and channel in Settings first."
                )
            discord = client_for(target)
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

    def serialize(event: Event) -> dict[str, Any]:
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
            "closes_at": event.closes_at,
            "published_at": event.published_at,
            "archived_at": event.archived_at,
            "signup_deleted_at": event.signup_deleted_at,
            "close_error": event.close_error or event.reaction_error,
            "is_test": bool(event.test_signups),
            "test_generation": event.test_signups.get("generation")
            if event.test_signups
            else None,
            "test_user_count": len(event.test_signups["players"])
            if event.test_signups
            else 0,
            "discord_url": (
                f"https://discord.com/channels/{event.guild_id}/"
                f"{event.channel_id or config.discord_channel_id}/{event.message_id}"
            )
            if event.message_id and not event.signup_deleted_at
            else None,
        }

    @app.get("/api/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/health/ready")
    def ready() -> dict[str, str]:
        try:
            with DBSession(engine) as db:
                db.execute(text("SELECT 1"))
                db.execute(select(Event.id).limit(1))
        except Exception:
            raise HTTPException(503, "Database is not ready.") from None
        return {"status": "ok"}

    @app.get("/api/setup")
    def setup() -> dict[str, bool]:
        return {"configured": config.configured}

    def begin_login(return_to: str = "", user_id: str | None = None) -> Response:
        if not config.configured:
            raise HTTPException(
                503, "Complete Discord configuration before signing in."
            )
        token = secrets.token_urlsafe(32)
        with DBSession(engine) as db:
            db.execute(delete(LoginState).where(LoginState.expires < time.time()))
            db.execute(delete(Session).where(Session.expires < time.time()))
            db.add(
                LoginState(
                    token_hash=digest(token),
                    expires=time.time() + 600,
                    purpose="connect" if user_id else "login",
                    user_id=user_id,
                )
            )
            db.commit()
        params = {
            "client_id": config.discord_client_id,
            "response_type": "code",
            "scope": "identify guilds bot" if user_id else "identify guilds",
            "redirect_uri": config.callback_url,
            "state": token,
        }
        if user_id:
            params.update(
                permissions=str(
                    POLL_PERMISSIONS
                    if config.discord_signup_mode == "poll"
                    else SIGNUP_PERMISSIONS
                ),
                integration_type="0",
                prompt="consent",
            )
        response = RedirectResponse(
            "https://discord.com/oauth2/authorize?" + urlencode(params)
        )
        cookie(response, "oauth_state", token, 600)
        cookie(
            response, "oauth_return", "settings" if return_to == "settings" else "", 600
        )
        return response

    @app.get("/api/auth/login")
    def login(return_to: str = "") -> Response:
        return begin_login(return_to)

    @app.get("/api/auth/connect")
    def connect(request: Request) -> Response:
        session = authenticated(request, require_destination=False)
        return begin_login("settings", session.user_id)

    @app.get("/api/auth/callback")
    def callback(
        request: Request, code: str = "", state: str = "", guild_id: str = ""
    ) -> Response:
        if not state or not secrets.compare_digest(
            state, request.cookies.get("oauth_state", "")
        ):
            raise HTTPException(400, "Invalid login state. Start sign-in again.")
        with DBSession(engine) as db:
            consumed = db.execute(
                delete(LoginState)
                .where(
                    LoginState.token_hash == digest(state),
                    LoginState.expires > time.time(),
                )
                .returning(LoginState.purpose, LoginState.user_id)
            ).first()
            db.commit()
            if not consumed or not code:
                raise HTTPException(400, "Login expired or cancelled. Sign in again.")
            if consumed.purpose == "connect":
                current = authenticated(request, require_destination=False)
                if current.user_id != consumed.user_id:
                    raise HTTPException(
                        403,
                        "Connection was started by another account. "
                        "Start Connect again.",
                    )
            user = app.state.discord.identity(code)
            if consumed.purpose == "connect":
                if user["id"] != consumed.user_id:
                    raise HTTPException(
                        403, "Authorize with the Discord account you signed in with."
                    )
                authorized = user.get("authorized_guild") or {}
                chosen_id = str(authorized.get("id") or guild_id)
                if not re.fullmatch(r"[0-9]{1,32}", chosen_id):
                    raise HTTPException(
                        400,
                        "Discord did not return the authorized server. "
                        "Start Connect again.",
                    )
                if authorized.get("id") and guild_id and chosen_id != guild_id:
                    raise HTTPException(
                        400, "Discord server did not match the authorization."
                    )
                # guild_id is only a hint; verify manager and bot access.
                guild, _, _ = app.state.discord.manager_context(user["id"], chosen_id)
                if str(guild.get("id")) != chosen_id:
                    raise HTTPException(502, "Could not verify the authorized server.")
                previous = db.get(UserSettings, user["id"])
                keep_channel = (
                    previous is not None
                    and not previous.disconnected
                    and previous.guild_id == chosen_id
                )
                db.merge(
                    UserSettings(
                        user_id=user["id"],
                        disconnected=False,
                        guild_id=chosen_id,
                        guild_name=str(guild["name"]),
                        channel_id=previous.channel_id
                        if keep_channel and previous
                        else "",
                        channel_name=previous.channel_name
                        if keep_channel and previous
                        else "",
                    )
                )
            token = secrets.token_urlsafe(32)
            db.execute(
                delete(Session).where(
                    Session.token_hash == digest(request.cookies.get("session", ""))
                )
            )
            db.add(
                Session(
                    token_hash=digest(token),
                    user_id=user["id"],
                    username=user["username"],
                    guilds=[
                        {"id": str(g["id"]), "name": str(g["name"])}
                        for g in user.get("guilds", [])
                        if g.get("owner") or int(g.get("permissions", "0")) & (8 | 32)
                    ],
                    csrf=secrets.token_urlsafe(32),
                    expires=time.time() + 28800,
                )
            )
            db.merge(UserIdentity(id=user["id"], username=user["username"]))
            db.commit()
        response = RedirectResponse(
            config.public_url + "/#/settings"
            if consumed.purpose == "connect"
            or request.cookies.get("oauth_return") == "settings"
            else config.public_url
        )
        response.delete_cookie("oauth_state", path="/api")
        response.delete_cookie("oauth_return", path="/api")
        cookie(response, "session", token, 28800)
        return response

    @app.get("/api/me")
    def me(request: Request) -> dict[str, Any]:
        session = authenticated(request, require_destination=False)
        with DBSession(engine) as db:
            db.merge(UserIdentity(id=session.user_id, username=session.username))
            db.commit()
            saved = db.get(UserSettings, session.user_id)
            selected = db.get(OrganizationSelection, session.user_id)
            organization = (
                db.get(Organization, selected.organization_id) if selected else None
            )
            membership = (
                db.get(OrganizationMember, (organization.id, session.user_id))
                if organization
                else None
            )
            if organization and membership is None:
                organization = None
            selection = (
                (
                    "disconnected"
                    if saved.disconnected
                    else f"{saved.guild_id}:{saved.channel_id}"
                )
                if saved
                else "legacy"
            )
        needs_setup = (
            False
            if organization
            else (
                (saved.disconnected or not saved.channel_id)
                if saved
                else not legacy_access(session.user_id)
            )
        )
        return {
            "username": session.username,
            "user_id": session.user_id,
            "csrf": session.csrf,
            "needs_setup": needs_setup,
            "destination": selection,
            "organization": {"id": organization.id, "name": organization.name}
            if organization
            else None,
            "organization_role": membership.role
            if organization and membership
            else None,
            "can_populate_test_users": test_users_allowed(session.user_id, config),
        }

    def organization_data(
        db: DBSession, org: Organization, user_id: str
    ) -> dict[str, Any]:
        member = db.get(OrganizationMember, (org.id, user_id))
        return {
            "id": org.id,
            "name": org.name,
            "created_by": org.created_by,
            "role": member.role if member else None,
        }

    @app.get("/api/organizations")
    def organizations(request: Request) -> dict[str, Any]:
        session = authenticated(request, require_destination=False)
        with DBSession(engine) as db:
            memberships = db.scalars(
                select(OrganizationMember).where(
                    OrganizationMember.user_id == session.user_id
                )
            ).all()
            selected = db.get(OrganizationSelection, session.user_id)
            return {
                "selected_id": selected.organization_id if selected else None,
                "organizations": [
                    organization_data(db, org, session.user_id)
                    for membership in memberships
                    if (org := db.get(Organization, membership.organization_id))
                    is not None
                ],
            }

    @app.post("/api/organizations", status_code=201)
    def create_organization(
        body: OrganizationInput, request: Request
    ) -> dict[str, Any]:
        session = authenticated(request, True, require_destination=False)
        name = body.name.strip()
        if not name or len(name.casefold()) > 100:
            raise HTTPException(422, "Choose a name of up to 100 characters")
        with DBSession(engine) as db:
            saved = db.get(UserSettings, session.user_id)
            if saved and not saved.disconnected and saved.guild_id and saved.channel_id:
                guild_id, channel_id = saved.guild_id, saved.channel_id
            elif (
                legacy_access(session.user_id)
                and config.discord_guild_id
                and config.discord_channel_id
            ):
                guild_id, channel_id = (
                    config.discord_guild_id,
                    config.discord_channel_id,
                )
            else:
                raise HTTPException(
                    409,
                    "Connect a Discord server and channel first",
                )
            org = Organization(
                id=str(uuid.uuid4()),
                name=name,
                normalized_name=name.casefold(),
                created_by=session.user_id,
                guild_id=guild_id,
                channel_id=channel_id,
            )
            db.add(org)
            db.add(
                OrganizationMember(
                    organization_id=org.id, user_id=session.user_id, role="admin"
                )
            )
            try:
                db.commit()
            except IntegrityError:
                raise HTTPException(
                    409, "Organization name is already in use"
                ) from None
            return organization_data(db, org, session.user_id)

    @app.put("/api/organizations/selection")
    def select_organization(
        body: OrganizationSelectionInput, request: Request
    ) -> dict[str, Any]:
        session = authenticated(request, True, require_destination=False)
        with DBSession(engine) as db:
            if (
                body.organization_id
                and db.get(OrganizationMember, (body.organization_id, session.user_id))
                is None
            ):
                raise HTTPException(403, "You are not a member of this organization")
            if body.organization_id:
                db.merge(
                    OrganizationSelection(
                        user_id=session.user_id, organization_id=body.organization_id
                    )
                )
            else:
                db.execute(
                    delete(OrganizationSelection).where(
                        OrganizationSelection.user_id == session.user_id
                    )
                )
            db.commit()
        return {"ok": True}

    @app.get("/api/organizations/users")
    def find_organization_users(request: Request, q: str = "") -> list[dict[str, str]]:
        session = authenticated(request, require_destination=False)
        if len(q.strip()) < 2:
            return []
        with DBSession(engine) as db:
            if not db.scalar(
                select(OrganizationMember.organization_id)
                .where(
                    OrganizationMember.user_id == session.user_id,
                    OrganizationMember.role == "admin",
                )
                .limit(1)
            ):
                raise HTTPException(403, "Admin access required")
            pattern = f"%{q.strip().casefold()}%"
            return [
                {"id": user.id, "username": user.username}
                for user in db.scalars(
                    select(UserIdentity)
                    .where(
                        func.lower(UserIdentity.username).like(pattern)
                        | UserIdentity.id.like(pattern)
                    )
                    .limit(20)
                )
            ]

    def require_org_admin(db: DBSession, org_id: str, user_id: str) -> Organization:
        org = db.get(Organization, org_id)
        member = db.get(OrganizationMember, (org_id, user_id))
        if org is None or member is None or member.role != "admin":
            raise HTTPException(403, "Organization admin access required")
        return org

    @app.get("/api/organizations/{org_id}/members")
    def organization_members(org_id: str, request: Request) -> list[dict[str, str]]:
        session = authenticated(request, require_destination=False)
        with DBSession(engine) as db:
            if db.get(OrganizationMember, (org_id, session.user_id)) is None:
                raise HTTPException(403, "Organization membership required")
            members = db.scalars(
                select(OrganizationMember).where(
                    OrganizationMember.organization_id == org_id
                )
            ).all()
            return [
                {
                    "user_id": member.user_id,
                    "username": (
                        identity.username
                        if (identity := db.get(UserIdentity, member.user_id))
                        else member.user_id
                    ),
                    "role": member.role,
                }
                for member in members
            ]

    @app.put("/api/organizations/{org_id}/members/{user_id}")
    def save_organization_member(
        org_id: str, user_id: str, body: OrganizationMemberInput, request: Request
    ) -> dict[str, str]:
        session = authenticated(request, True, require_destination=False)
        if body.user_id != user_id or body.role not in ("user", "editor", "admin"):
            raise HTTPException(422, "Invalid member or permission")
        with DBSession(engine) as db:
            org = require_org_admin(db, org_id, session.user_id)
            if user_id == org.created_by:
                raise HTTPException(403, "Creator permissions cannot be changed")
            if db.get(UserIdentity, user_id) is None:
                raise HTTPException(404, "User not found")
            db.merge(
                OrganizationMember(
                    organization_id=org_id, user_id=user_id, role=body.role
                )
            )
            db.commit()
        return {"ok": "true"}

    @app.delete("/api/organizations/{org_id}/members/me", status_code=204)
    def leave_organization(org_id: str, request: Request) -> Response:
        session = authenticated(request, True, require_destination=False)
        with DBSession(engine) as db:
            org = db.get(Organization, org_id)
            if (
                org is None
                or db.get(OrganizationMember, (org_id, session.user_id)) is None
            ):
                raise HTTPException(404, "Organization not found")
            if org.created_by == session.user_id:
                raise HTTPException(409, "Creator must delete the organization")
            db.execute(
                delete(OrganizationSelection).where(
                    OrganizationSelection.user_id == session.user_id,
                    OrganizationSelection.organization_id == org_id,
                )
            )
            db.execute(
                delete(OrganizationMember).where(
                    OrganizationMember.organization_id == org_id,
                    OrganizationMember.user_id == session.user_id,
                )
            )
            db.commit()
        return Response(status_code=204)

    @app.delete("/api/organizations/{org_id}/members/{user_id}", status_code=204)
    def remove_organization_member(
        org_id: str, user_id: str, request: Request
    ) -> Response:
        session = authenticated(request, True, require_destination=False)
        with DBSession(engine) as db:
            org = require_org_admin(db, org_id, session.user_id)
            if user_id == org.created_by:
                raise HTTPException(403, "The creator cannot be removed")
            if user_id == session.user_id:
                raise HTTPException(409, "Use Leave organization to remove yourself")
            member = db.get(OrganizationMember, (org_id, user_id))
            if member is None:
                raise HTTPException(404, "Organization member not found")
            db.execute(
                delete(OrganizationSelection).where(
                    OrganizationSelection.user_id == user_id,
                    OrganizationSelection.organization_id == org_id,
                )
            )
            db.delete(member)
            db.commit()
        return Response(status_code=204)

    @app.delete("/api/organizations/{org_id}", status_code=204)
    def delete_organization(org_id: str, request: Request) -> Response:
        session = authenticated(request, True, require_destination=False)
        with DBSession(engine) as db:
            org = db.get(Organization, org_id)
            if org is None or org.created_by != session.user_id:
                raise HTTPException(
                    403, "Only the creator can delete this organization"
                )
            db.execute(
                update(Event)
                .where(Event.organization_id == org_id)
                .values(organization_id=None)
            )
            db.execute(
                delete(OrganizationSelection).where(
                    OrganizationSelection.organization_id == org_id
                )
            )
            db.execute(
                delete(OrganizationMember).where(
                    OrganizationMember.organization_id == org_id
                )
            )
            db.delete(org)
            db.commit()
        return Response(status_code=204)

    @app.post("/api/auth/logout")
    def logout(request: Request) -> Response:
        session = authenticated(request, True, require_destination=False)
        with DBSession(engine) as db:
            db.execute(delete(Session).where(Session.token_hash == session.token_hash))
            db.commit()
        response = Response(status_code=204)
        response.delete_cookie("session", path="/api")
        return response

    register_settings(app, engine, config, authenticated, legacy_access)

    @app.get("/api/settings/assignment")
    def assignment_settings(request: Request) -> dict[str, Any]:
        authenticated(request, require_channel=False)
        guild_id = destination(request).discord_guild_id
        with DBSession(engine) as db:
            saved = db.get(GuildSettings, guild_id)
            return {
                "automatic_weight_adjustment": saved.automatic_weight_adjustment
                if saved
                else True
            }

    @app.put("/api/settings/assignment")
    def save_assignment_settings(
        body: AssignmentSettingsInput, request: Request
    ) -> dict[str, Any]:
        authenticated(request, True, require_channel=False)
        with DBSession(engine) as db:
            db.merge(
                GuildSettings(
                    guild_id=destination(request).discord_guild_id,
                    automatic_weight_adjustment=body.automatic_weight_adjustment,
                )
            )
            db.commit()
        return {"automatic_weight_adjustment": body.automatic_weight_adjustment}

    def discord_name(player_id: str) -> str:
        discord: DiscordAPI = app.state.discord
        user = discord.bot("GET", f"/users/{player_id}")
        name = user.get("global_name") or user.get("username")
        if not isinstance(name, str) or not name:
            raise HTTPException(502, "Discord returned an invalid user profile")
        return name

    def player_data(
        player_id: str, profile: PlayerProfile | None, signup_name: str | None = None
    ) -> dict[str, Any]:
        return {
            "discord_id": player_id,
            "discord_name": profile.discord_name
            if profile
            else signup_name or discord_name(player_id),
            "real_name": profile.real_name if profile else "",
            "weighting": profile.weighting if profile else 1.0,
            "is_test": profile.is_test if profile else False,
            "guaranteed_seat": profile.guaranteed_seat if profile else False,
        }

    def valid_player_id(player_id: str) -> None:
        if re.fullmatch(r"test-[a-f0-9]{24}", player_id):
            return
        if not player_id.isascii() or not player_id.isdecimal() or len(player_id) > 32:
            raise HTTPException(422, "Invalid Discord user ID")

    @app.get("/api/players")
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

    @app.get("/api/players/{player_id}")
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

    @app.put("/api/players/{player_id}")
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
                    weighting=body.weighting if body.weighting is not None else 1.0,
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

    @app.get("/api/events")
    def events(request: Request) -> list[dict[str, Any]]:
        authenticated(request)
        with DBSession(engine) as db:
            return [
                serialize(event)
                for event in db.scalars(
                    select(Event).where(*event_scope(request)).order_by(Event.starts_at)
                )
            ]

    def serialize_template(template: EventTemplate) -> dict[str, Any]:
        return {
            "id": template.id,
            "title": template.title,
            "description": template.description,
            "location": template.location,
            "duration_hours": template.duration_hours,
            "tables": template.tables,
        }

    @app.get("/api/templates")
    def templates(request: Request) -> list[dict[str, Any]]:
        session = authenticated(request, require_destination=False)
        with DBSession(engine) as db:
            return [
                serialize_template(template)
                for template in db.scalars(
                    select(EventTemplate)
                    .where(EventTemplate.user_id == session.user_id)
                    .order_by(EventTemplate.created_at.desc(), EventTemplate.id)
                )
            ]

    @app.post("/api/templates", status_code=201)
    def create_template(body: EventTemplateInput, request: Request) -> dict[str, Any]:
        session = authenticated(request, True, require_destination=False)
        with DBSession(engine) as db:
            template = EventTemplate(
                id=str(uuid.uuid4()),
                user_id=session.user_id,
                title=body.title.strip(),
                description=body.description.strip(),
                location=body.location.strip(),
                duration_hours=body.duration_hours,
                tables=[table.model_dump() for table in body.tables],
                created_at=time.time(),
            )
            db.add(template)
            db.commit()
            return serialize_template(template)

    def list_names(
        rows: list[dict[str, Any]], guild_id: str, event_id: str | None = None
    ) -> list[dict[str, Any]]:
        # Decorate copies for the app; saved results keep Discord names.
        with DBSession(engine) as db:
            profiles = {
                profile.discord_id: profile
                for profile in db.scalars(
                    select(PlayerProfile).where(
                        PlayerProfile.guild_id == guild_id,
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
                        else 1.0
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

    @app.get("/api/events/{event_id}/signups")
    def event_signups(event_id: str, request: Request) -> list[dict[str, Any]]:
        authenticated(request)
        custom_result: tuple[list[dict[str, Any]], str] | None = None
        with DBSession(engine) as db:
            event = db.get(Event, event_id)
            if event is None or not matches_destination(event, request):
                raise HTTPException(404, "Event not found")
            if event.status == "assigned":
                run = db.get(LotteryRun, event_id)
                if run is None:
                    raise HTTPException(503, "Saved placements are unavailable")
                rows: list[dict[str, Any]] = current_result(db, run)["tables"]
                return list_names(rows, event.guild_id)
            message_id = event.message_id
            tables = event.tables
            population = event.test_signups
            if event.signup_mode in ("custom", "reactions"):
                custom_result = (
                    apply_manager_signups(
                        db, event, add_to_rows(table_rows(db, event), population)
                    ),
                    event.guild_id,
                )
                db.rollback()
        if custom_result is not None:
            return list_names(custom_result[0], custom_result[1], event_id)
        rows = (
            scoped_discord(request).table_signups(message_id, tables)
            if message_id
            else [{"name": table["name"], "players": []} for table in tables]
        )
        with DBSession(engine) as db:
            event = db.get(Event, event_id)
            if event is None or not matches_destination(event, request):
                raise HTTPException(404, "Event not found")
            rows = apply_manager_signups(db, event, add_to_rows(rows, population))
            guild_id = event.guild_id
            db.rollback()
        return list_names(rows, guild_id, event_id)

    @app.get("/api/events/{event_id}/signups.csv")
    def download_event_csv(event_id: str, request: Request) -> Response:
        with DBSession(engine) as db:
            event = db.get(Event, event_id)
            authenticated(request)
            if event is None or not matches_destination(event, request):
                raise HTTPException(404, "Event not found")
            if event.status != "assigned":
                raise HTTPException(409, "Signups must be assigned before export")
        rows = event_signups(event_id, request)
        return Response(
            event_csv(rows),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="signups-{event_id}.csv"'
            },
        )

    @app.get("/api/events/{event_id}/signups.pdf")
    def download_event_pdf(
        event_id: str, request: Request, timezone: str = "UTC"
    ) -> Response:
        authenticated(request)
        try:
            time_zone = ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise HTTPException(400, "Invalid timezone") from None
        with DBSession(engine) as db:
            event = db.get(Event, event_id)
            if event is None or not matches_destination(event, request):
                raise HTTPException(404, "Event not found")
            if event.status != "assigned":
                raise HTTPException(409, "Signups must be assigned before export")
            rows = event_signups(event_id, request)
            content = event_pdf(event, rows, time_zone)
        return Response(
            content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="signups-{event_id}.pdf"'
            },
        )

    @app.get("/api/exports/signups.csv")
    def download_summary_csv(request: Request) -> Response:
        authenticated(request)
        with DBSession(engine) as db:
            selected = list(
                db.scalars(
                    select(Event)
                    .where(*event_scope(request))
                    .order_by(Event.starts_at, Event.id)
                )
            )
            data = [(event, event_signups(event.id, request)) for event in selected]
            content = summary_csv(data)
        return Response(
            content,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="all-event-signups.csv"'
            },
        )

    @app.put("/api/events/{event_id}/manager-players/{player_id}")
    def add_manager_player(
        event_id: str, player_id: str, body: ManagerSignupInput, request: Request
    ) -> dict[str, Any]:
        authenticated(request, True)
        valid_player_id(player_id)
        with DBSession(engine) as db:
            claimed = db.execute(
                update(Event)
                .where(
                    Event.id == event_id,
                    *event_scope(request),
                    Event.status.in_(["draft", "open"]),
                )
                .values(status=Event.status)
                .returning(Event.id)
            ).scalar_one_or_none()
            if not claimed:
                raise HTTPException(409, "Only draft or open signups can be changed")
            event = db.get(Event, event_id)
            assert event is not None
            if body.table not in {table["name"] for table in event.tables}:
                raise HTTPException(422, "Unknown table")
            profile = db.get(PlayerProfile, (event.guild_id, player_id))
            if player_id.startswith("test-") and (
                profile is None or not profile.is_test
            ):
                raise HTTPException(404, "Player not found")
            override = db.get(EventManagerSignup, (event_id, player_id))
            if override is None:
                override = EventManagerSignup(
                    event_id=event_id,
                    discord_id=player_id,
                    discord_name=body.name.strip(),
                    choices=[body.table],
                    removed=False,
                )
                db.add(override)
            else:
                override.discord_name = body.name.strip()
                override.choices = sorted(set(override.choices) | {body.table})
                override.removed = False
            db.commit()
            return {"ok": True}

    @app.post("/api/events/{event_id}/assigned-players/{player_id}")
    def add_assigned_player(
        event_id: str, player_id: str, body: AssignedAddInput, request: Request
    ) -> dict[str, Any]:
        authenticated(request, True)
        valid_player_id(player_id)
        with DBSession(engine) as db:
            event = db.get(Event, event_id)
            if event is None or not matches_destination(event, request):
                raise HTTPException(404, "Event not found")
            guild_id = event.guild_id
        if not manager_add(engine, guild_id, event_id, player_id, body.table):
            raise HTTPException(409, "Player is not available on this table's waitlist")
        return {"ok": True}

    @app.delete("/api/events/{event_id}/manager-players/{player_id}")
    def remove_manager_player(
        event_id: str, player_id: str, request: Request
    ) -> dict[str, Any]:
        authenticated(request, True)
        valid_player_id(player_id)
        with DBSession(engine) as db:
            event = db.get(Event, event_id)
            if event is None or not matches_destination(event, request):
                raise HTTPException(404, "Event not found")
            assigned_guild = event.guild_id if event.status == "assigned" else None
        if assigned_guild:
            if not manager_remove(engine, assigned_guild, event_id, player_id):
                raise HTTPException(409, "Player is not currently assigned")
            return {"ok": True}
        with DBSession(engine) as db:
            claimed = db.execute(
                update(Event)
                .where(
                    Event.id == event_id,
                    *event_scope(request),
                    Event.status.in_(["draft", "open"]),
                )
                .values(status=Event.status)
                .returning(Event.id)
            ).scalar_one_or_none()
            if not claimed:
                raise HTTPException(409, "Only draft or open signups can be changed")
            event = db.get(Event, event_id)
            assert event is not None
            override = db.get(EventManagerSignup, (event_id, player_id))
            if override is None:
                override = EventManagerSignup(
                    event_id=event_id,
                    discord_id=player_id,
                    discord_name="",
                    choices=[],
                    removed=True,
                )
                db.add(override)
            else:
                override.choices = []
                override.removed = True
            if event.signup_mode in ("custom", "reactions"):
                signup = db.get(TableSignup, (event_id, player_id))
                if signup is not None:
                    db.delete(signup)
            db.commit()
            return {"ok": True}

    @app.put("/api/events/{event_id}/players/{player_id}/settings")
    def save_event_player_setting(
        event_id: str, player_id: str, body: EventPlayerSettingInput, request: Request
    ) -> dict[str, Any]:
        authenticated(request, True)
        valid_player_id(player_id)
        fields = body.model_fields_set
        if not fields or not fields <= {"weighting", "guaranteed_table"}:
            raise HTTPException(422, "Specify a weight or guaranteed table")
        with DBSession(engine) as db:
            # Serialize edits against the closing claim.
            claimed = db.execute(
                update(Event)
                .where(
                    Event.id == event_id, *event_scope(request), Event.status == "open"
                )
                .values(status=Event.status)
                .returning(Event.id)
            ).scalar_one_or_none()
            if not claimed:
                raise HTTPException(409, "Only open signups can be changed")
            event = db.get(Event, event_id)
            assert event is not None
            if "guaranteed_table" in fields and body.guaranteed_table is not None:
                if body.guaranteed_table not in {
                    table["name"] for table in event.tables
                }:
                    raise HTTPException(422, "Unknown table")
                signed_up = any(
                    p["id"] == player_id and body.guaranteed_table in p["choices"]
                    for p in (event.test_signups or {}).get("players", [])
                )
                if event.signup_mode in ("custom", "reactions"):
                    signup = db.get(TableSignup, (event_id, player_id))
                    signed_up = signed_up or bool(
                        signup and body.guaranteed_table in signup.choices
                    )
                elif event.message_id and not signed_up:
                    signed_up = any(
                        row["name"] == body.guaranteed_table
                        and any(p["id"] == player_id for p in row["players"])
                        for row in scoped_discord(request).table_signups(
                            event.message_id, event.tables
                        )
                    )
                if not signed_up:
                    raise HTTPException(422, "Player is not signed up for that table")
            setting = db.get(EventPlayerSetting, (event_id, player_id))
            if setting is None:
                setting = EventPlayerSetting(event_id=event_id, discord_id=player_id)
                db.add(setting)
            if "weighting" in fields:
                setting.weighting = body.weighting
            if "guaranteed_table" in fields:
                setting.guaranteed_table = body.guaranteed_table
            db.commit()
            profile = db.get(PlayerProfile, (event.guild_id, player_id))
            return {
                "weighting": setting.weighting
                if setting.weighting is not None
                else profile.weighting
                if profile
                else 1.0,
                "guaranteed_table": setting.guaranteed_table,
                "guaranteed_seat": profile.guaranteed_seat if profile else False,
            }

    @app.post("/api/events/{event_id}/close")
    def close_signups(
        event_id: str, request: Request, delete_signup_message: bool = False
    ) -> Response:
        session = authenticated(request, True)
        with DBSession(engine) as db:
            event = db.get(Event, event_id)
            if event is None or not matches_destination(event, request):
                raise HTTPException(404, "Event not found")
        complete = close_and_assign(
            engine,
            scoped_discord(request),
            event_id,
            session.user_id,
            destination(request).discord_channel_id,
        )
        if complete:
            if (
                event.signup_mode == "reactions"
                and event.message_id
                and not event.signup_deleted_at
            ):
                try:
                    scoped_discord(request).close_reaction_message(event.message_id)
                except Exception:
                    logging.getLogger(__name__).exception(
                        "Could not mark the reaction message closed; "
                        "late reactions are rejected"
                    )
            if (
                event.signup_mode == "custom"
                and event.message_id
                and not event.signup_deleted_at
            ):
                try:
                    scoped_discord(request).close_signup_message(event.message_id)
                except Exception:
                    logging.getLogger(__name__).exception(
                        "Could not remove closed signup controls; "
                        "further signups are rejected"
                    )
            try:
                deliver_event(engine, scoped_discord(request), event_id)
            except Exception:
                logging.getLogger(__name__).exception(
                    "Immediate announcement attempt failed; delivery remains queued"
                )
            if delete_signup_message:
                with DBSession(engine) as db:
                    saved = db.get(Event, event_id)
                    assert saved is not None
                    remove_signup_message(db, saved, request)
                    db.commit()
        with DBSession(engine) as db:
            event = db.get(Event, event_id)
            assert event is not None
            return JSONResponse(serialize(event), status_code=200 if complete else 202)

    @app.post("/api/events/{event_id}/test-users")
    def populate_test_users(
        event_id: str, body: TestPopulationInput, request: Request
    ) -> dict[str, Any]:
        session = authenticated(request, True)
        if not test_users_allowed(session.user_id, config):
            raise HTTPException(
                403, "Test signup population is restricted to allowlisted operators"
            )
        with DBSession(engine) as db:
            event = db.get(Event, event_id)
            if event is None or not matches_destination(event, request):
                raise HTTPException(404, "Event not found")
            population = (
                generate_test_users(event_id, event.tables, body.players)
                if body.players
                else None
            )
            changed = db.execute(
                update(Event)
                .where(
                    Event.id == event_id,
                    *event_scope(request),
                    Event.status.in_(["draft", "open"]),
                )
                .values(test_signups=population)
                .returning(Event.id)
            ).scalar_one_or_none()
            if not changed:
                raise HTTPException(
                    409, "Test users can only be changed before signups close"
                )
            saved_tests = (
                list(
                    db.scalars(
                        select(PlayerProfile)
                        .where(
                            PlayerProfile.guild_id == event.guild_id,
                            PlayerProfile.is_test.is_(True),
                        )
                        .order_by(PlayerProfile.discord_name, PlayerProfile.discord_id)
                        .limit(body.players)
                    )
                )
                if population
                else []
            )
            for index, player in enumerate(population["players"] if population else []):
                if index < len(saved_tests):
                    saved = saved_tests[index]
                    player.update(
                        id=saved.discord_id,
                        name=saved.discord_name,
                        weight=saved.weighting,
                    )
                else:
                    player["name"] = f"Test Player {index + 1:03d}"
                    player["weight"] = 1.0
                    db.add(
                        PlayerProfile(
                            guild_id=event.guild_id,
                            discord_id=player["id"],
                            discord_name=player["name"],
                            real_name="",
                            weighting=1.0,
                            is_test=True,
                        )
                    )
            # Persist the final identities after reusing saved profiles.
            db.execute(
                update(Event)
                .where(Event.id == event_id)
                .values(test_signups=population)
            )
            db.commit()
            db.refresh(event)
            return serialize(event)

    @app.get("/api/events/{event_id}/announcement")
    def announcement(event_id: str, request: Request) -> dict[str, Any]:
        authenticated(request)
        with DBSession(engine) as db:
            event = db.get(Event, event_id)
            if event is None or not matches_destination(event, request):
                raise HTTPException(404, "Event not found")
            guild_id = event.guild_id
        return announcement_status(engine, event_id, guild_id)

    @app.post("/api/events/{event_id}/announcement/retry")
    def retry_announcement(
        event_id: str, body: RetryAnnouncementInput, request: Request
    ) -> dict[str, Any]:
        authenticated(request, True)
        with DBSession(engine) as db:
            event = db.get(Event, event_id)
            if event is None or not matches_destination(event, request):
                raise HTTPException(404, "Event not found")
            run = db.get(LotteryRun, event_id)
            if event.status != "assigned" or run is None:
                raise HTTPException(409, "Placements have not been determined yet")
            if event.archived_at is not None:
                raise HTTPException(409, "Archived events cannot be announced again")
            existing = db.scalar(
                select(Announcement.id)
                .where(Announcement.event_id == event_id)
                .limit(1)
            )
            creating = existing is None
            announcement_channel = (
                event.channel_id or destination(request).discord_channel_id
            )
            if creating:
                enqueue(db, event, announcement_channel, run.result, run.snapshot)
            else:
                enqueue_instructions(db, event, announcement_channel)
            rows = list(
                db.scalars(
                    select(Announcement).where(
                        Announcement.event_id == event_id,
                        Announcement.kind.in_(["assignment", "instructions"]),
                        Announcement.state != "sent",
                    )
                )
            )
            if any(row.state == "sending" or row.token for row in rows):
                raise HTTPException(409, "Announcement delivery is already in progress")
            if (
                any(row.unknown or row.state == "needs_review" for row in rows)
                and not body.confirm_repost
            ):
                raise HTTPException(
                    409, "Check Discord before confirming a possible repost"
                )
            for row in rows:
                changed = db.execute(
                    update(Announcement)
                    .where(
                        Announcement.id == row.id,
                        Announcement.state.in_(["pending", "needs_review"]),
                        Announcement.token.is_(None),
                        Announcement.attempts == row.attempts,
                    )
                    .values(
                        state="pending",
                        next_attempt=time.time(),
                        unknown=False,
                        lease_until=None,
                        error=None,
                    )
                    .returning(Announcement.id)
                ).scalar_one_or_none()
                if not changed:
                    db.rollback()
                    raise HTTPException(
                        409, "Delivery changed while retrying. Refresh its status."
                    )
            guild_id = event.guild_id
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                if not creating or not db.scalar(
                    select(Announcement.id)
                    .where(Announcement.event_id == event_id)
                    .limit(1)
                ):
                    raise
        deliver_event(engine, scoped_discord(request), event_id)
        return announcement_status(engine, event_id, guild_id)

    @app.get("/api/events/{event_id}/assignments")
    def assignments(event_id: str, request: Request) -> dict[str, Any]:
        authenticated(request)
        with DBSession(engine) as db:
            event = db.get(Event, event_id)
            if event is None or not matches_destination(event, request):
                raise HTTPException(404, "Event not found")
            run = db.get(LotteryRun, event_id)
            if run is None:
                raise HTTPException(409, "Placements have not been determined yet")
            return {
                "version": run.version,
                "seed": run.seed,
                "snapshot": run.snapshot,
                "result": run.result,
                "current_result": current_result(db, run),
                "created_at": run.created_at,
            }

    @app.post("/api/events", status_code=201)
    def create_event(body: EventInput, request: Request) -> dict[str, Any]:
        session = authenticated(request, True)
        with DBSession(engine) as db:
            event = Event(
                id=str(uuid.uuid4()),
                guild_id=destination(request).discord_guild_id,
                channel_id=destination(request).discord_channel_id,
                title=body.title.strip(),
                description=body.description.strip(),
                location=body.location.strip(),
                starts_at=body.starts_at.timestamp(),
                duration_hours=body.duration_hours,
                tables=[table.model_dump() for table in body.tables],
                created_by=session.user_id,
                organization_id=request.state.organization_id,
                status="draft",
            )
            db.add(event)
            db.commit()
            return serialize(event)

    @app.put("/api/events/{event_id}")
    def edit_event(event_id: str, body: EventInput, request: Request) -> dict[str, Any]:
        authenticated(request, True)
        with DBSession(engine) as db:
            changed = db.execute(
                update(Event)
                .where(
                    Event.id == event_id,
                    *event_scope(request),
                    Event.status == "draft",
                )
                .values(
                    title=body.title.strip(),
                    description=body.description.strip(),
                    location=body.location.strip(),
                    starts_at=body.starts_at.timestamp(),
                    duration_hours=body.duration_hours,
                    tables=[table.model_dump() for table in body.tables],
                )
                .returning(Event.id)
            ).scalar_one_or_none()
            if not changed:
                raise HTTPException(409, "Only unpublished drafts can be edited.")
            db.commit()
            event = db.get(Event, event_id)
            assert event is not None
            return serialize(event)

    def remove_signup_message(db: DBSession, event: Event, request: Request) -> None:
        if event.message_id and not event.signup_deleted_at:
            scoped_discord(request).at(
                event.guild_id, event.channel_id or config.discord_channel_id
            ).delete_poll(event.message_id)
            event.signup_deleted_at = time.time()

    @app.post("/api/events/{event_id}/signup-message/delete")
    def delete_signup_message(event_id: str, request: Request) -> dict[str, Any]:
        authenticated(request, True)
        with DBSession(engine) as db:
            event = db.get(Event, event_id)
            if event is None or not matches_destination(event, request):
                raise HTTPException(404, "Event not found")
            if event.status != "assigned":
                raise HTTPException(409, "Close signups before deleting the message")
            remove_signup_message(db, event, request)
            db.commit()
            return serialize(event)

    def delete_discord_messages_batch(
        event_id: str, request: Request, promotions_only: bool = False
    ) -> dict[str, Any]:
        with DBSession(engine) as db:
            event = db.get(Event, event_id)
            if event is None or not matches_destination(event, request):
                raise HTTPException(404, "Event not found")
            if event.status != "assigned" or event.archived_at is None:
                raise HTTPException(
                    409, "Archive the event before deleting its messages"
                )
            query = select(Announcement).where(Announcement.event_id == event_id)
            if promotions_only:
                query = query.where(Announcement.kind == "promotion")
            rows = list(db.scalars(query.order_by(Announcement.part)))

            def progress(
                retry_after: float = 0, error: str | None = None
            ) -> dict[str, Any]:
                remaining = sum(not row.deleted_at for row in rows)
                if not promotions_only:
                    remaining += bool(event.message_id and not event.signup_deleted_at)
                return {
                    **serialize(event),
                    "discord_cleanup_remaining": remaining,
                    "discord_cleanup_retry_after": retry_after,
                    "discord_cleanup_error": error,
                }

            def failed(failure: DiscordRequestError) -> dict[str, Any]:
                if failure.discord_status == 429:
                    return progress(
                        retry_after=failure.retry_after
                        if failure.retry_after > 0
                        else 1
                    )
                status = failure.discord_status or "network"
                return progress(
                    error=f"Discord deletion failed ({status}). "
                    "Retry the remaining messages."
                )

            now = time.time()
            for row in rows:
                if row.kind == "promotion" and (
                    row.unknown or row.state == "needs_review"
                ):
                    discord = scoped_discord(request).at(event.guild_id, row.channel_id)
                    message_id = None
                    try:
                        message_id = discord.find_announcement(
                            row.channel_id,
                            row.payload,
                            row.attempted_at or row.created_at,
                        )
                        if message_id:
                            discord.delete_poll(message_id)
                    except DiscordRequestError as failure:
                        if message_id:
                            row.message_id = message_id
                            row.state = "sent"
                            row.error = "Promotion notice deletion failed."
                            db.commit()
                        return failed(failure)
                    except HTTPException as failure:
                        return progress(
                            error=f"Promotion notice cleanup failed: {failure.detail}"
                        )
                    row.message_id = message_id
                    row.state = "sent"
                    row.deleted_at = now
                    row.unknown = False
                    row.error = None
                if (
                    promotions_only
                    and row.kind == "promotion"
                    and row.state in ("pending", "needs_review")
                    and not row.message_id
                    and not row.unknown
                ):
                    row.state = "sent"
                    row.deleted_at = now
                    row.token = None
                    row.lease_until = None
            db.commit()

            if any(row.state == "needs_review" for row in rows):
                return progress(
                    error="An assignment announcement needs review before its "
                    "Discord messages can be deleted."
                )
            if any(
                not row.deleted_at and (row.state != "sent" or not row.message_id)
                for row in rows
            ):
                return progress(retry_after=2)
            targets = [row for row in rows if not row.deleted_at]
            for row in targets if promotions_only else targets[:3]:
                assert row.message_id is not None
                try:
                    scoped_discord(request).at(
                        event.guild_id, row.channel_id
                    ).delete_poll(row.message_id)
                except DiscordRequestError as failure:
                    return failed(failure)
                row.deleted_at = time.time()
                db.commit()
            if (
                not promotions_only
                and len(targets) < 3
                and event.message_id
                and not event.signup_deleted_at
            ):
                try:
                    remove_signup_message(db, event, request)
                except DiscordRequestError as failure:
                    return failed(failure)
                db.commit()
            return progress()

    @app.post("/api/events/{event_id}/discord-messages/delete")
    def delete_discord_messages(event_id: str, request: Request) -> dict[str, Any]:
        authenticated(request, True)
        return delete_discord_messages_batch(event_id, request)

    @app.post("/api/events/{event_id}/archive")
    def archive_event(
        event_id: str, request: Request, delete_discord_messages: bool = False
    ) -> dict[str, Any]:
        authenticated(request, True)
        with DBSession(engine) as db:
            event = db.get(Event, event_id)
            if event is None or not matches_destination(event, request):
                raise HTTPException(404, "Event not found")
            if event.status != "assigned" or db.get(LotteryRun, event_id) is None:
                raise HTTPException(409, "Only assigned events can be archived")
            db.execute(
                update(Event)
                .where(
                    Event.id == event_id,
                    *event_scope(request),
                    Event.status == "assigned",
                    Event.archived_at.is_(None),
                )
                .values(archived_at=time.time())
            )
            db.commit()
        return delete_discord_messages_batch(
            event_id, request, promotions_only=not delete_discord_messages
        )

    @app.delete("/api/events/{event_id}", status_code=204)
    def delete_event(
        event_id: str, request: Request, delete_poll: bool = False
    ) -> Response:
        authenticated(request, True)
        with DBSession(engine) as db:
            # Claim deletion atomically, keeping the transaction open until the
            # optional Discord operation succeeds. Failures roll back this row.
            changed = db.execute(
                delete(Event)
                .where(
                    Event.id == event_id,
                    *event_scope(request),
                    Event.status.in_(["draft", "open"]),
                )
                .returning(Event.message_id)
            ).first()
            if changed is None:
                raise HTTPException(409, "Only drafts and open signups can be deleted.")
            if delete_poll and changed.message_id:
                scoped_discord(request).delete_poll(changed.message_id)
            db.execute(delete(TableSignup).where(TableSignup.event_id == event_id))
            db.execute(
                delete(SignupInteraction).where(SignupInteraction.event_id == event_id)
            )
            db.commit()
        return Response(status_code=204)

    @app.post("/api/events/{event_id}/publish")
    def publish(event_id: str, request: Request) -> dict[str, Any]:
        authenticated(request, True)
        if config.discord_signup_mode == "custom" and config.discord_gateway_enabled:
            gateway = getattr(app.state, "gateway", None)
            if gateway is None or not gateway.is_ready():
                raise HTTPException(
                    503,
                    "Discord signup listener is not connected. Check the API logs, "
                    "bot token, and that Discord's Interactions Endpoint URL is blank.",
                )
        with DBSession(engine) as db:
            event = db.get(Event, event_id)
            if not event or not matches_destination(event, request):
                raise HTTPException(404, "Event not found")
            if event.starts_at <= time.time() + event.duration_hours * 3600:
                raise HTTPException(
                    400, "Signup window would end after the event starts"
                )
            claimed = db.execute(
                update(Event)
                .where(Event.id == event_id, Event.status == "draft")
                .values(
                    status="publishing",
                    signup_mode=(
                        "reactions"
                        if config.discord_signup_mode == "custom"
                        else "poll"
                    ),
                )
                .returning(Event.id)
            ).scalar_one_or_none()
            db.commit()
            if not claimed:
                raise HTTPException(409, "Already published or awaiting publish review")
            db.refresh(event)
            try:
                closes_at = time.time() + event.duration_hours * 3600
                message = scoped_discord(request).publish(
                    reaction_publication(event, closes_at)
                    if event.signup_mode == "reactions"
                    else {
                        "content": (
                            f"**{'[TEST] ' if event.test_signups else ''}"
                            f"{event.title}**\n"
                            f"Event: <t:{int(event.starts_at)}:F>\n"
                            f"{signup_location(event.location)}"
                            f"Signups open for {event.duration_hours} hours. "
                            f"{signup_description(event.description, POLL_DESCRIPTION)}"
                        ),
                        "allowed_mentions": {"parse": []},
                        "poll": {
                            "question": {"text": "Which tables would you attend?"},
                            "answers": [
                                {
                                    "poll_media": {
                                        "text": f"{t['name']} · {t['capacity']} seats"
                                    }
                                }
                                for t in event.tables
                            ],
                            "duration": event.duration_hours,
                            "allow_multiselect": True,
                        },
                    }
                )
                event.published_at = (
                    datetime.fromisoformat(message["timestamp"]).timestamp()
                    if message.get("timestamp")
                    else time.time()
                )
                event.message_id = str(message["id"])
                if event.signup_mode == "reactions":
                    event.closes_at = closes_at
                    # Save the message identity before seeding: an uncertain PUT
                    # must never cause a second publication on retry.
                    db.commit()
                    scoped_discord(request).seed_reactions(
                        event.message_id, list(EMOJIS[: len(event.tables)])
                    )
                else:
                    event.answers = message["poll"]["answers"]
                    event.closes_at = datetime.fromisoformat(
                        message["poll"]["expiry"]
                    ).timestamp()
                event.status = "open"
                db.commit()
            except Exception:
                db.rollback()
                db.execute(
                    update(Event)
                    .where(Event.id == event_id)
                    .values(status="needs_review")
                )
                db.commit()
                raise HTTPException(
                    502,
                    "Publish could not be confirmed. Check Discord "
                    "before retrying; this event is held for review.",
                ) from None
            return serialize(event)

    return app


app = create_app()
