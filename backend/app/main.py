import hashlib
import secrets
import time
import uuid
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import create_engine, delete, select, text, update
from sqlalchemy.orm import Session as DBSession

from app.config import Settings
from app.discord_api import DiscordAPI
from app.models import Event, LoginState, Schedule, Session
from app.publication import publish_event
from app.scheduling import ScheduleInput, materialize, preview, schedule_data
from app.schemas import EventInput


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    engine = create_engine(config.database_url, pool_pre_ping=True)
    app = FastAPI(title="Table registration")
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

    def authenticated(request: Request, mutation: bool = False) -> Session:
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
            app.state.discord.authorize(session.user_id)
            return session

    def serialize(event: Event) -> dict[str, Any]:
        return {
            "id": event.id,
            "title": event.title,
            "starts_at": event.starts_at,
            "timezone": event.timezone,
            "opens_at": event.opens_at,
            "signup_closes_at": event.signup_closes_at,
            "duration_hours": event.duration_hours,
            "tables": event.tables,
            "status": event.status,
            "closes_at": event.closes_at,
            "last_error": event.last_error,
            "schedule_id": event.schedule_id,
            "occurrence_date": event.occurrence_date,
            "overridden": event.overridden,
            "discord_url": (
                f"https://discord.com/channels/{config.discord_guild_id}/"
                f"{config.discord_channel_id}/{event.message_id}"
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
    def login() -> Response:
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
                    "scope": "identify",
                    "redirect_uri": config.callback_url,
                    "state": token,
                }
            )
        )
        cookie(response, "oauth_state", token, 600)
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
            app.state.discord.authorize(user["id"])
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
                    csrf=secrets.token_urlsafe(32),
                    expires=time.time() + 28800,
                )
            )
            db.commit()
        response = RedirectResponse(config.public_url)
        response.delete_cookie("oauth_state", path="/api")
        cookie(response, "session", token, 28800)
        return response

    @app.get("/api/me")
    def me(request: Request) -> dict[str, str]:
        session = authenticated(request)
        return {"username": session.username, "csrf": session.csrf}

    @app.post("/api/auth/logout")
    def logout(request: Request) -> Response:
        session = authenticated(request, True)
        with DBSession(engine) as db:
            db.execute(delete(Session).where(Session.token_hash == session.token_hash))
            db.commit()
        response = Response(status_code=204)
        response.delete_cookie("session", path="/api")
        return response

    @app.get("/api/events")
    def events(request: Request) -> list[dict[str, Any]]:
        authenticated(request)
        with DBSession(engine) as db:
            return [
                serialize(event)
                for event in db.scalars(
                    select(Event)
                    .where(Event.guild_id == config.discord_guild_id)
                    .order_by(Event.starts_at)
                )
            ]

    @app.post("/api/events", status_code=201)
    def create_event(body: EventInput, request: Request) -> dict[str, Any]:
        session = authenticated(request, True)
        with DBSession(engine) as db:
            event = Event(
                id=str(uuid.uuid4()),
                guild_id=config.discord_guild_id,
                title=body.title.strip(),
                starts_at=body.starts_at.timestamp(),
                duration_hours=body.duration_hours,
                tables=[table.model_dump() for table in body.tables],
                created_by=session.user_id,
                status="draft",
                timezone=body.timezone,
                opens_at=body.opens_at.timestamp() if body.opens_at else None,
                signup_closes_at=body.signup_closes_at.timestamp()
                if body.signup_closes_at
                else None,
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
                    Event.guild_id == config.discord_guild_id,
                    Event.status == "draft",
                )
                .values(
                    timezone=body.timezone,
                    opens_at=body.opens_at.timestamp() if body.opens_at else None,
                    signup_closes_at=body.signup_closes_at.timestamp()
                    if body.signup_closes_at
                    else None,
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
    def delete_event(event_id: str, request: Request) -> Response:
        authenticated(request, True)
        with DBSession(engine) as db:
            changed = db.execute(
                delete(Event)
                .where(
                    Event.id == event_id,
                    Event.guild_id == config.discord_guild_id,
                    Event.status == "draft",
                )
                .returning(Event.id)
            ).scalar_one_or_none()
            if not changed:
                raise HTTPException(409, "Only unpublished drafts can be deleted.")
            db.commit()
        return Response(status_code=204)

    @app.post("/api/events/{event_id}/publish")
    def publish(event_id: str, request: Request) -> dict[str, Any]:
        authenticated(request, True)
        publish_event(engine, app.state.discord, config, event_id)
        with DBSession(engine) as db:
            event = db.get(Event, event_id)
            assert event is not None
            return serialize(event)

    @app.post("/api/events/{event_id}/schedule")
    def schedule_event(event_id: str, request: Request) -> dict[str, Any]:
        authenticated(request, True)
        now = time.time()
        with DBSession(engine) as db:
            claimed = db.execute(
                update(Event)
                .where(
                    Event.id == event_id,
                    Event.guild_id == config.discord_guild_id,
                    Event.status == "draft",
                    Event.opens_at > now,
                    Event.signup_closes_at > Event.opens_at,
                    Event.starts_at > Event.signup_closes_at,
                )
                .values(status="scheduled")
                .returning(Event.id)
            ).scalar_one_or_none()
            if not claimed:
                raise HTTPException(
                    409, "Only future drafts with valid signup times can be scheduled"
                )
            db.commit()
            event = db.get(Event, event_id)
            assert event is not None
            return serialize(event)

    @app.get("/api/schedules")
    def schedules(request: Request) -> list[dict[str, Any]]:
        authenticated(request)
        with DBSession(engine) as db:
            return [
                schedule_data(s)
                for s in db.scalars(
                    select(Schedule)
                    .where(Schedule.guild_id == config.discord_guild_id)
                    .order_by(Schedule.title)
                )
            ]

    @app.post("/api/schedules/preview")
    def schedule_preview(body: ScheduleInput, request: Request) -> list[dict[str, Any]]:
        authenticated(request, True)
        return preview(body)

    @app.post("/api/schedules", status_code=201)
    def create_schedule(body: ScheduleInput, request: Request) -> dict[str, Any]:
        session = authenticated(request, True)
        rows = preview(body)
        if any(row.get("error") and not row["skipped"] for row in rows):
            raise HTTPException(
                422, "Correct or explicitly skip the invalid dates shown in the preview"
            )
        with DBSession(engine) as db:
            schedule = Schedule(
                id=str(uuid.uuid4()),
                guild_id=config.discord_guild_id,
                title=body.title.strip(),
                timezone=body.timezone,
                rule=body.model_dump(
                    mode="json", exclude={"title", "timezone", "tables"}
                ),
                tables=[t.model_dump() for t in body.tables],
                created_by=session.user_id,
                active=True,
            )
            db.add(schedule)
            db.flush()
            materialize(db, schedule)
            db.commit()
            return schedule_data(schedule)

    return app


app = create_app()
