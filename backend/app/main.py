import hashlib
import secrets
import time
import uuid
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import create_engine, delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.config import Settings
from app.discord_api import DiscordAPI
from app.models import Event, LiveVote, LoginState, Schedule, Session
from app.publication import publish_event
from app.recovery import RecoveryInput, recover_event
from app.scheduling import (
    ScheduleActivation,
    ScheduleEditInput,
    ScheduleInput,
    materialize,
    preview,
    schedule_data,
    update_occurrences,
)
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
        with DBSession(engine) as db:
            live_count = db.scalar(
                select(func.count(func.distinct(LiveVote.user_id))).where(
                    LiveVote.event_id == event.id
                )
            )
        return {
            "live_signup_count": live_count,
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
            "message_id": event.message_id,
            "signup_count": len(event.voter_snapshot)
            if event.voter_snapshot is not None
            else None,
            "reconciled_at": event.reconciled_at,
            "recovery_audit": event.recovery_audit,
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
            current = db.get(Event, event_id)
            if (
                current
                and current.status in ("scheduled", "paused")
                and body.opens_at is None
            ):
                raise HTTPException(
                    409, "Scheduled events must retain explicit signup times"
                )
            changed = db.execute(
                update(Event)
                .where(
                    Event.id == event_id,
                    Event.guild_id == config.discord_guild_id,
                    Event.status.in_(["draft", "scheduled", "paused"]),
                )
                .values(
                    overridden=Event.schedule_id.is_not(None),
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
        key = request.headers.get("idempotency-key")
        try:
            schedule_id = str(uuid.UUID(key)) if key else str(uuid.uuid4())
        except ValueError:
            raise HTTPException(422, "Invalid request key") from None
        rows = preview(body)
        if any(row.get("error") and not row["skipped"] for row in rows):
            raise HTTPException(
                422, "Correct or explicitly skip the invalid dates shown in the preview"
            )
        with DBSession(engine) as db:
            previous = db.get(Schedule, schedule_id)
            if previous:
                if (
                    previous.guild_id != config.discord_guild_id
                    or ScheduleInput.model_validate(schedule_data(previous)) != body
                ):
                    raise HTTPException(
                        409, "This request key was used; refresh schedules"
                    )
                return schedule_data(previous)
            schedule = Schedule(
                id=schedule_id,
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
            try:
                db.flush()
                materialize(db, schedule)
                db.commit()
            except IntegrityError:
                db.rollback()
                raise HTTPException(
                    409, "Schedule already created; refresh schedules"
                ) from None
            return schedule_data(schedule)

    @app.post("/api/schedules/{schedule_id}/preview")
    def edit_schedule_preview(
        schedule_id: str, body: ScheduleEditInput, request: Request
    ) -> list[dict[str, Any]]:
        authenticated(request, True)
        with DBSession(engine) as db:
            schedule = db.get(Schedule, schedule_id)
            if not schedule or schedule.guild_id != config.discord_guild_id:
                raise HTTPException(404, "Schedule not found")
            if schedule.revision != body.revision:
                raise HTTPException(409, "Schedule changed; refresh before editing")
            rows = preview(body)
            existing = {
                e.occurrence_date: e
                for e in db.scalars(
                    select(Event).where(Event.schedule_id == schedule_id)
                )
            }
            for row in rows:
                event = existing.get(row["date"])
                row["action"] = (
                    "preserved"
                    if event
                    and (
                        event.overridden
                        or event.status not in ("scheduled", "paused", "cancelled")
                    )
                    else ("skip" if row["skipped"] else "update" if event else "create")
                )
            for day, event in existing.items():
                if day not in {r["date"] for r in rows} and event.status in (
                    "scheduled",
                    "paused",
                ):
                    rows.append(
                        {
                            "date": day,
                            "skipped": False,
                            "action": "preserved" if event.overridden else "cancel",
                        }
                    )
            return rows

    @app.put("/api/schedules/{schedule_id}")
    def edit_schedule(
        schedule_id: str, body: ScheduleEditInput, request: Request
    ) -> dict[str, Any]:
        authenticated(request, True)
        with DBSession(engine) as db:
            schedule = db.scalar(
                select(Schedule)
                .where(
                    Schedule.id == schedule_id,
                    Schedule.guild_id == config.discord_guild_id,
                )
                .with_for_update()
            )
            if not schedule:
                raise HTTPException(404, "Schedule not found")
            if schedule.revision != body.revision:
                raise HTTPException(409, "Schedule changed; refresh before editing")
            protected = set(
                db.scalars(
                    select(Event.occurrence_date).where(
                        Event.schedule_id == schedule_id,
                        (
                            Event.overridden.is_(True)
                            | Event.status.not_in(["scheduled", "paused", "cancelled"])
                        ),
                    )
                )
            )
            if any(
                row.get("error") and not row["skipped"] and row["date"] not in protected
                for row in preview(body)
            ):
                raise HTTPException(422, "Correct or skip invalid preview dates")
            claimed = db.execute(
                update(Schedule)
                .where(Schedule.id == schedule_id, Schedule.revision == body.revision)
                .values(revision=Schedule.revision + 1)
                .returning(Schedule.id)
            ).scalar_one_or_none()
            if not claimed:
                raise HTTPException(409, "Schedule changed; refresh before editing")
            schedule.title = body.title.strip()
            schedule.timezone = body.timezone
            schedule.rule = body.model_dump(
                mode="json", exclude={"title", "timezone", "tables", "revision"}
            )
            schedule.tables = [t.model_dump() for t in body.tables]
            update_occurrences(db, schedule)
            db.commit()
            return schedule_data(schedule)

    @app.post("/api/schedules/{schedule_id}/active")
    def toggle_schedule(
        schedule_id: str, body: ScheduleActivation, request: Request
    ) -> dict[str, Any]:
        authenticated(request, True)
        with DBSession(engine) as db:
            schedule = db.scalar(
                select(Schedule)
                .where(
                    Schedule.id == schedule_id,
                    Schedule.guild_id == config.discord_guild_id,
                )
                .with_for_update()
            )
            if not schedule:
                raise HTTPException(404, "Schedule not found")
            if schedule.revision != body.revision:
                raise HTTPException(409, "Schedule changed; refresh before editing")
            claimed = db.execute(
                update(Schedule)
                .where(Schedule.id == schedule_id, Schedule.revision == body.revision)
                .values(revision=Schedule.revision + 1)
                .returning(Schedule.id)
            ).scalar_one_or_none()
            if not claimed:
                raise HTTPException(409, "Schedule changed; refresh before editing")
            schedule.active = body.active
            db.execute(
                update(Event)
                .where(
                    Event.schedule_id == schedule_id,
                    Event.status == ("paused" if schedule.active else "scheduled"),
                )
                .values(status="scheduled" if schedule.active else "paused")
            )
            if schedule.active:
                materialize(db, schedule)
            db.commit()
            return schedule_data(schedule)

    @app.post("/api/events/{event_id}/cancel")
    def cancel_occurrence(event_id: str, request: Request) -> dict[str, Any]:
        authenticated(request, True)
        with DBSession(engine) as db:
            event = db.get(Event, event_id)
            if not event or event.guild_id != config.discord_guild_id:
                raise HTTPException(404, "Event not found")
            status = event.status
            if status not in ("draft", "scheduled", "paused", "open"):
                raise HTTPException(
                    409, "This event cannot be cancelled safely; check its status"
                )
            claimed = db.execute(
                update(Event)
                .where(Event.id == event_id, Event.status == status)
                .values(
                    status="cancelling",
                    operation_started_at=time.time(),
                    overridden=True,
                )
                .returning(Event.id)
            ).scalar_one_or_none()
            db.commit()
            if not claimed:
                raise HTTPException(409, "Event changed; refresh before cancelling")
            db.refresh(event)
            try:
                if (
                    status == "open"
                    and event.message_id
                    and event.closes_at
                    and event.closes_at > time.time()
                ):
                    app.state.discord.bot(
                        "POST",
                        f"/channels/{config.discord_channel_id}/polls/{event.message_id}/expire",
                    )
                event.status = "cancelled"
                event.operation_started_at = None
                db.commit()
            except Exception:
                db.rollback()
                db.execute(
                    update(Event)
                    .where(Event.id == event_id)
                    .values(
                        status="needs_review",
                        last_error="Cancellation uncertain; check Discord.",
                    )
                )
                db.commit()
                raise HTTPException(
                    502, "Cancellation could not be confirmed; check Discord"
                ) from None
            return serialize(event)

    @app.post("/api/events/{event_id}/recover")
    def recover(event_id: str, body: RecoveryInput, request: Request) -> dict[str, Any]:
        session = authenticated(request, True)
        recover_event(
            engine, app.state.discord, config, event_id, body, session.user_id
        )
        with DBSession(engine) as db:
            event = db.get(Event, event_id)
            assert event is not None
            return serialize(event)

    return app


app = create_app()
