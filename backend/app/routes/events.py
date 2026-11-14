"""Events API routes."""

import time
import uuid
from functools import partial
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session as DBSession

from app.context import ApplicationContext
from app.models import (
    CanceledOccurrence,
    Event,
    EventTemplate,
    RecurringSeries,
)
from app.publication import publish_event as publish_event_service
from app.recurrence import fill_schedule
from app.schemas import (
    EventInput,
    EventTemplateInput,
    RecurringInput,
)
from app.signup_warnings import settings as warning_settings


def register(context: ApplicationContext) -> None:
    router = APIRouter()
    app = context.app
    authenticated = context.authenticated
    config = context.config
    destination = context.destination
    engine = context.engine
    event_scope = context.event_scope
    matches_destination = context.matches_destination
    scoped_discord = context.scoped_discord
    serialize = context.serialize
    publish_event = partial(publish_event_service, context)

    @router.get("/api/events")
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
            **warning_settings(template),
            "id": template.id,
            "title": template.title,
            "description": template.description,
            "location": template.location,
            "duration_hours": template.duration_hours,
            "tables": template.tables,
        }

    @router.get("/api/templates")
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

    @router.post("/api/templates", status_code=201)
    def create_template(body: EventTemplateInput, request: Request) -> dict[str, Any]:
        session = authenticated(request, True, require_destination=False)
        with DBSession(engine) as db:
            template = EventTemplate(
                **warning_settings(body),
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

    @router.post("/api/events", status_code=201)
    def create_event(body: EventInput, request: Request) -> dict[str, Any]:
        session = authenticated(request, True)
        with DBSession(engine) as db:
            event = Event(
                **warning_settings(body),
                id=str(uuid.uuid4()),
                guild_id=destination(request).discord_guild_id,
                channel_id=destination(request).discord_channel_id,
                title=body.title.strip(),
                description=body.description.strip(),
                location=body.location.strip(),
                starts_at=body.starts_at.timestamp(),
                scheduled_publish_at=body.starts_at.timestamp()
                - body.opens_before_hours * 3600
                if body.opens_before_hours is not None
                else None,
                closes_at=body.starts_at.timestamp() - body.closes_before_hours * 3600
                if body.closes_before_hours is not None
                else None,
                duration_hours=body.duration_hours,
                tables=[table.model_dump() for table in body.tables],
                created_by=session.user_id,
                organization_id=request.state.organization_id,
                status="draft",
            )
            db.add(event)
            db.commit()
            return serialize(event)

    @router.get("/api/recurring-series")
    def recurring_series(request: Request) -> list[dict[str, Any]]:
        authenticated(request)
        with DBSession(engine) as db:
            target = destination(request)
            rows = db.scalars(
                select(RecurringSeries).where(
                    RecurringSeries.organization_id == request.state.organization_id
                    if request.state.organization_id
                    else RecurringSeries.organization_id.is_(None)
                    & (RecurringSeries.created_by == request.state.user_id),
                    RecurringSeries.guild_id == target.discord_guild_id,
                    RecurringSeries.channel_id == target.discord_channel_id,
                    RecurringSeries.active,
                )
            )
            return [
                {
                    "id": row.id,
                    "title": row.title,
                    "frequency": row.frequency,
                    "time_zone": row.time_zone,
                    "opens_before_hours": row.opens_before_hours,
                    "closes_before_hours": row.closes_before_hours,
                }
                for row in rows
            ]

    @router.post("/api/recurring-series", status_code=201)
    def create_recurring_series(
        body: RecurringInput, request: Request
    ) -> dict[str, Any]:
        session = authenticated(request, True)
        target = destination(request)
        with DBSession(engine) as db:
            series = RecurringSeries(
                **warning_settings(body),
                id=str(uuid.uuid4()),
                created_by=session.user_id,
                organization_id=request.state.organization_id,
                guild_id=target.discord_guild_id,
                channel_id=target.discord_channel_id,
                title=body.title.strip(),
                description=body.description.strip(),
                location=body.location.strip(),
                tables=[table.model_dump() for table in body.tables],
                first_local=body.starts_at.astimezone(
                    ZoneInfo(body.time_zone)
                ).strftime("%Y-%m-%dT%H:%M"),
                time_zone=body.time_zone,
                frequency=body.frequency,
                opens_before_hours=body.opens_before_hours,
                closes_before_hours=body.closes_before_hours,
                active=True,
            )
            db.add(series)
            fill_schedule(db, series, time.time())
            db.commit()
            return {"id": series.id, "title": series.title}

    @router.post("/api/recurring-series/{series_id}/stop")
    def stop_recurring_series(series_id: str, request: Request) -> Response:
        authenticated(request, True)
        target = destination(request)
        with DBSession(engine) as db:
            series = db.get(RecurringSeries, series_id)
            if (
                not series
                or series.organization_id != request.state.organization_id
                or (
                    series.organization_id is None
                    and series.created_by != request.state.user_id
                )
                or series.guild_id != target.discord_guild_id
                or series.channel_id != target.discord_channel_id
            ):
                raise HTTPException(404, "Schedule not found")
            series.active = False
            db.execute(
                delete(Event).where(
                    Event.series_id == series_id, Event.status == "scheduled"
                )
            )
            db.commit()
        return Response(status_code=204)

    @router.post("/api/events/{event_id}/cancel-scheduled")
    def cancel_scheduled(event_id: str, request: Request) -> Response:
        authenticated(request, True)
        with DBSession(engine) as db:
            event = db.get(Event, event_id)
            if not event or not matches_destination(event, request):
                raise HTTPException(404, "Event not found")
            if event.status != "scheduled" or not event.series_id:
                raise HTTPException(
                    409, "Only unposted scheduled events can be canceled"
                )
            removed = db.execute(
                delete(Event)
                .where(Event.id == event_id, Event.status == "scheduled")
                .returning(Event.series_id, Event.starts_at)
            ).first()
            if not removed or not removed.series_id:
                raise HTTPException(409, "This event has already started publishing")
            db.add(
                CanceledOccurrence(
                    series_id=removed.series_id, starts_at=removed.starts_at
                )
            )
            series = db.get(RecurringSeries, removed.series_id)
            db.flush()
            if series:
                fill_schedule(db, series, time.time())
            db.commit()
        return Response(status_code=204)

    @router.put("/api/events/{event_id}")
    def edit_event(event_id: str, body: EventInput, request: Request) -> dict[str, Any]:
        authenticated(request, True)
        with DBSession(engine) as db:
            changed = db.execute(
                update(Event)
                .where(
                    Event.id == event_id,
                    *event_scope(request),
                    Event.status.in_(["draft", "scheduled"]),
                )
                .values(
                    **warning_settings(body),
                    title=body.title.strip(),
                    description=body.description.strip(),
                    location=body.location.strip(),
                    starts_at=body.starts_at.timestamp(),
                    scheduled_publish_at=body.starts_at.timestamp()
                    - body.opens_before_hours * 3600
                    if body.opens_before_hours is not None
                    else None,
                    closes_at=body.starts_at.timestamp()
                    - body.closes_before_hours * 3600
                    if body.closes_before_hours is not None
                    else None,
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

    @router.post("/api/events/{event_id}/publish")
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
            status = event.status
            if status not in ("draft", "scheduled"):
                raise HTTPException(409, "Already published or awaiting publish review")
        return publish_event(event_id, scoped_discord(request), status, force=True)

    context.app.include_router(router)
