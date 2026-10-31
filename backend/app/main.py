import hashlib
import secrets
import time
import uuid
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import create_engine, delete, select, text, update
from sqlalchemy.orm import Session as DBSession

from app.config import Settings
from app.discord_api import DiscordAPI
from app.models import Event, LoginState, Session


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
            "duration_hours": event.duration_hours,
            "tables": event.tables,
            "status": event.status,
            "closes_at": event.closes_at,
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

    @app.get("/api/events/{event_id}/signups")
    def event_signups(event_id: str, request: Request) -> list[dict[str, Any]]:
        authenticated(request)
        with DBSession(engine) as db:
            event = db.get(Event, event_id)
            if event is None or event.guild_id != config.discord_guild_id:
                raise HTTPException(404, "Event not found")
            if not event.message_id:
                return [{"name": t["name"], "players": []} for t in event.tables]
            answers = {
                answer.get("poll_media", {}).get("text"): answer["answer_id"]
                for answer in event.answers or []
            }
            rows = []
            for table in event.tables:
                label = f"{table['name']} · {table['capacity']} seats"
                if label not in answers:
                    raise HTTPException(
                        502, "Cannot match Discord poll answers to tables"
                    )
                rows.append(
                    {
                        "name": table["name"],
                        "players": app.state.discord.voters(
                            event.message_id, answers[label]
                        ),
                    }
                )
            return rows

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
        with DBSession(engine) as db:
            event = db.get(Event, event_id)
            if not event or event.guild_id != config.discord_guild_id:
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
                message = app.state.discord.publish(
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
