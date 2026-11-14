"""Generate a small, durable window of future events for a series."""

import calendar
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CanceledOccurrence, Event, RecurringSeries
from app.signup_warnings import settings as warning_settings


def occurrence(series: RecurringSeries, index: int) -> float | None:
    first = datetime.fromisoformat(series.first_local)
    if series.frequency == "daily":
        local = first + timedelta(days=index)
    elif series.frequency == "weekly":
        local = first + timedelta(weeks=index)
    else:
        month = first.year * 12 + first.month - 1 + index
        year, month_zero = divmod(month, 12)
        month_number = month_zero + 1
        if first.day > calendar.monthrange(year, month_number)[1]:
            return None
        local = first.replace(year=year, month=month_number)
    zone = ZoneInfo(series.time_zone)
    aware = local.replace(tzinfo=zone)
    # A wall time in the spring DST gap does not exist.
    if datetime.fromtimestamp(aware.timestamp(), zone).replace(tzinfo=None) != local:
        return None
    return aware.timestamp()


def fill_schedule(db: Session, series: RecurringSeries, now: float) -> None:
    # Refresh after acquiring the lock: a worker may have loaded the old schedule.
    db.flush()
    db.refresh(series, with_for_update=True)
    if not series.active:
        return
    occupied = set(
        db.scalars(
            select(Event.series_slot_at)
            .where(Event.source_series_id == series.id)
            .union(select(Event.starts_at).where(Event.source_series_id == series.id))
        )
    )
    future = set(
        db.scalars(
            select(Event.starts_at).where(
                Event.series_id == series.id,
                Event.starts_at > now,
                Event.archived_at.is_(None),
            )
        )
    )
    canceled = set(
        db.scalars(
            select(CanceledOccurrence.starts_at).where(
                CanceledOccurrence.series_id == series.id
            )
        )
    )
    index = 0
    while len(future) < 4 and index < 20000:
        start = occurrence(series, index)
        index += 1
        if start is None or start <= now or start in occupied or start in canceled:
            continue
        publish_at = start - series.opens_before_hours * 3600
        if publish_at <= now:
            continue
        db.add(
            Event(
                **warning_settings(series),
                id=str(uuid.uuid4()),
                series_id=series.id,
                source_series_id=series.id,
                series_slot_at=start,
                scheduled_publish_at=publish_at,
                closes_at=start - series.closes_before_hours * 3600,
                guild_id=series.guild_id,
                channel_id=series.channel_id,
                title=series.title,
                description=series.description,
                location=series.location,
                starts_at=start,
                duration_hours=series.opens_before_hours - series.closes_before_hours,
                tables=series.tables,
                status="scheduled",
                created_by=series.created_by,
                organization_id=series.organization_id,
            )
        )
        future.add(start)
        occupied.add(start)
