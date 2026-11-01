import hashlib
import secrets
import time
import uuid
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import create_engine, delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.closing import close_and_assign
from app.config import Settings
from app.connection_settings import register_settings
from app.discord_api import DiscordAPI
from app.models import (
    Event,
    LoginState,
    LotteryRun,
    PlayerProfile,
    Session,
    UserSettings,
)


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


class PlayerProfileInput(BaseModel):
    model_config = {"extra": "forbid"}
    real_name: str = Field(max_length=100)

    @field_validator("real_name")
    @classmethod
    def clean_real_name(cls, value: str) -> str:
        return value.strip()


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    engine = create_engine(config.database_url, pool_pre_ping=True)
    app = FastAPI(title="TableSignup")
    app.state.engine = engine
    app.state.discord = DiscordAPI(config)

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

    def event_scope(request: Request) -> tuple[Any, Any]:
        target = destination(request)
        return (
            Event.guild_id == target.discord_guild_id,
            func.coalesce(Event.channel_id, config.discord_channel_id)
            == target.discord_channel_id,
        )

    def matches_destination(event: Event, request: Request) -> bool:
        target = destination(request)
        return (
            event.guild_id == target.discord_guild_id
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
        request: Request, mutation: bool = False, require_destination: bool = True
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
            if not require_destination:
                return session
            saved = db.get(UserSettings, session.user_id)
            target = (
                config.model_copy(
                    update={
                        "discord_guild_id": saved.guild_id,
                        "discord_channel_id": saved.channel_id,
                    }
                )
                if saved
                else config
            )
            if not target.discord_guild_id or not target.discord_channel_id:
                raise HTTPException(
                    409, "Choose a server and channel in Settings first."
                )
            discord = client_for(target)
            if saved:
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
            "starts_at": event.starts_at,
            "duration_hours": event.duration_hours,
            "tables": event.tables,
            "status": event.status,
            "closes_at": event.closes_at,
            "published_at": event.published_at,
            "close_error": event.close_error,
            "discord_url": (
                f"https://discord.com/channels/{event.guild_id}/"
                f"{event.channel_id or config.discord_channel_id}/{event.message_id}"
            )
            if event.message_id
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

    @app.get("/api/auth/login")
    def login(return_to: str = "") -> Response:
        if not config.configured:
            raise HTTPException(
                503, "Complete Discord configuration before signing in."
            )
        token = secrets.token_urlsafe(32)
        with DBSession(engine) as db:
            db.execute(delete(LoginState).where(LoginState.expires < time.time()))
            db.execute(delete(Session).where(Session.expires < time.time()))
            db.add(LoginState(token_hash=digest(token), expires=time.time() + 600))
            db.commit()
        response = RedirectResponse(
            "https://discord.com/oauth2/authorize?"
            + urlencode(
                {
                    "client_id": config.discord_client_id,
                    "response_type": "code",
                    "scope": "identify guilds",
                    "redirect_uri": config.callback_url,
                    "state": token,
                }
            )
        )
        cookie(response, "oauth_state", token, 600)
        cookie(
            response, "oauth_return", "settings" if return_to == "settings" else "", 600
        )
        return response

    @app.get("/api/auth/callback")
    def callback(request: Request, code: str = "", state: str = "") -> Response:
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
                .returning(LoginState.token_hash)
            ).scalar_one_or_none()
            db.commit()
            if not consumed or not code:
                raise HTTPException(400, "Login expired or cancelled. Sign in again.")
            user = app.state.discord.identity(code)
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
            db.commit()
        response = RedirectResponse(
            config.public_url + "/#/settings"
            if request.cookies.get("oauth_return") == "settings"
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
            saved = db.get(UserSettings, session.user_id)
            selection = f"{saved.guild_id}:{saved.channel_id}" if saved else "legacy"
        needs_setup = not saved and not legacy_access(session.user_id)
        return {
            "username": session.username,
            "csrf": session.csrf,
            "needs_setup": needs_setup,
            "destination": selection,
        }

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

    def discord_name(player_id: str) -> str:
        discord: DiscordAPI = app.state.discord
        user = discord.bot("GET", f"/users/{player_id}")
        name = user.get("global_name") or user.get("username")
        if not isinstance(name, str) or not name:
            raise HTTPException(502, "Discord returned an invalid user profile")
        return name

    def player_data(player_id: str, profile: PlayerProfile | None) -> dict[str, Any]:
        return {
            "discord_id": player_id,
            "discord_name": profile.discord_name
            if profile
            else discord_name(player_id),
            "real_name": profile.real_name if profile else "",
            "weighting": profile.weighting if profile else 1.0,
        }

    def valid_player_id(player_id: str) -> None:
        if not player_id.isascii() or not player_id.isdecimal() or len(player_id) > 32:
            raise HTTPException(422, "Invalid Discord user ID")

    @app.get("/api/players/{player_id}")
    def player_profile(player_id: str, request: Request) -> dict[str, Any]:
        authenticated(request)
        valid_player_id(player_id)
        with DBSession(engine) as db:
            profile = db.get(
                PlayerProfile, (destination(request).discord_guild_id, player_id)
            )
            return player_data(player_id, profile)

    @app.put("/api/players/{player_id}")
    def save_player_profile(
        player_id: str, body: PlayerProfileInput, request: Request
    ) -> dict[str, Any]:
        authenticated(request, True)
        valid_player_id(player_id)
        with DBSession(engine) as db:
            profile = db.get(
                PlayerProfile, (destination(request).discord_guild_id, player_id)
            )
            if profile is None:
                profile = PlayerProfile(
                    guild_id=destination(request).discord_guild_id,
                    discord_id=player_id,
                    discord_name=discord_name(player_id),
                    real_name=body.real_name,
                    weighting=1.0,
                )
                db.add(profile)
            else:
                profile.real_name = body.real_name
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
                profile.real_name = body.real_name
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

    @app.get("/api/events/{event_id}/signups")
    def event_signups(event_id: str, request: Request) -> list[dict[str, Any]]:
        authenticated(request)
        with DBSession(engine) as db:
            event = db.get(Event, event_id)
            if event is None or not matches_destination(event, request):
                raise HTTPException(404, "Event not found")
            if event.status == "assigned":
                run = db.get(LotteryRun, event_id)
                if run is None:
                    raise HTTPException(503, "Saved placements are unavailable")
                rows: list[dict[str, Any]] = run.result["tables"]
                return rows
            message_id = event.message_id
            tables = event.tables
        if not message_id:
            return [{"name": table["name"], "players": []} for table in tables]
        discord = scoped_discord(request)
        return discord.table_signups(message_id, tables)

    @app.post("/api/events/{event_id}/close")
    def close_signups(event_id: str, request: Request) -> Response:
        session = authenticated(request, True)
        with DBSession(engine) as db:
            event = db.get(Event, event_id)
            if event is None or not matches_destination(event, request):
                raise HTTPException(404, "Event not found")
        complete = close_and_assign(
            engine, scoped_discord(request), event_id, session.user_id
        )
        with DBSession(engine) as db:
            event = db.get(Event, event_id)
            assert event is not None
            return JSONResponse(serialize(event), status_code=200 if complete else 202)

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
                starts_at=body.starts_at.timestamp(),
                duration_hours=body.duration_hours,
                tables=[table.model_dump() for table in body.tables],
                created_by=session.user_id,
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
            db.commit()
        return Response(status_code=204)

    @app.post("/api/events/{event_id}/publish")
    def publish(event_id: str, request: Request) -> dict[str, Any]:
        authenticated(request, True)
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
                .values(status="publishing")
                .returning(Event.id)
            ).scalar_one_or_none()
            db.commit()
            if not claimed:
                raise HTTPException(409, "Already published or awaiting publish review")
            db.refresh(event)
            try:
                message = scoped_discord(request).publish(
                    {
                        "content": (
                            f"**{event.title}**\nEvent: <t:{int(event.starts_at)}:F>\n"
                            f"Signups open for {event.duration_hours} hours. "
                            "Select every table you would attend. "
                            "This is a lottery entry, not a guaranteed seat."
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
