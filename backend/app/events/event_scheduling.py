"""Shared form values and schedule serialization."""

import time
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.events.recurrence import occurrence
from app.events.signup_warnings import settings as warning_settings
from app.models import Event, RecurringSeries
from app.schemas import EventInput, RecurringInput


def event_values(body: EventInput) -> dict[str, Any]:
    start = body.starts_at.timestamp()
    return {
        **warning_settings(body),
        "title": body.title.strip(),
        "description": body.description.strip(),
        "location": body.location.strip(),
        "tables": [table.model_dump() for table in body.tables],
        "starts_at": start,
        "scheduled_publish_at": start - body.opens_before_hours * 3600
        if body.opens_before_hours is not None
        else None,
        "closes_at": start - body.closes_before_hours * 3600
        if body.closes_before_hours is not None
        else None,
        "duration_hours": body.opens_before_hours - body.closes_before_hours
        if body.opens_before_hours is not None and body.closes_before_hours is not None
        else body.duration_hours,
    }


def series_values(body: RecurringInput) -> dict[str, Any]:
    values = event_values(body)
    for field in ("starts_at", "scheduled_publish_at", "closes_at", "duration_hours"):
        values.pop(field)
    return {
        **values,
        "first_local": body.starts_at.astimezone(ZoneInfo(body.time_zone)).strftime(
            "%Y-%m-%dT%H:%M"
        ),
        "time_zone": body.time_zone,
        "frequency": body.frequency,
        "opens_before_hours": body.opens_before_hours,
        "closes_before_hours": body.closes_before_hours,
    }


def serialize_series(db: Session, series: RecurringSeries) -> dict[str, Any]:
    # Use the next nominal slot, even if that occurrence was moved individually.
    start = db.scalar(
        select(Event.series_slot_at)
        .where(
            Event.series_id == series.id,
            Event.status == "scheduled",
            Event.scheduled_publish_at > time.time(),
            Event.series_slot_at - series.opens_before_hours * 3600 > time.time(),
        )
        .order_by(Event.series_slot_at)
        .limit(1)
    )
    if start is None:
        for index in range(20000):
            candidate = occurrence(series, index)
            if (
                candidate is not None
                and candidate - series.opens_before_hours * 3600 > time.time()
            ):
                start = candidate
                break
    return {
        **warning_settings(series),
        "id": series.id,
        "title": series.title,
        "description": series.description,
        "location": series.location,
        "tables": series.tables,
        "starts_at": start,
        "duration_hours": series.opens_before_hours - series.closes_before_hours,
        "frequency": series.frequency,
        "time_zone": series.time_zone,
        "opens_before_hours": series.opens_before_hours,
        "closes_before_hours": series.closes_before_hours,
    }
