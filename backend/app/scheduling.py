import math
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from datetime import time as wall_time
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Event, Schedule
from app.schemas import EventInput, TableInput


def resolve_local(day: date, clock: wall_time, zone: str) -> float:
    naive = datetime.combine(day, clock)
    tz = ZoneInfo(zone)
    candidates = set()
    for fold in (0, 1):
        aware = naive.replace(tzinfo=tz, fold=fold)
        if aware.astimezone(UTC).astimezone(tz).replace(tzinfo=None) == naive:
            candidates.add(aware.timestamp())
    if len(candidates) != 1:
        raise ValueError(
            f"{day} {clock:%H:%M} in {zone} is missing or ambiguous; "
            "change the time or skip this date"
        )
    return candidates.pop()


class ScheduleInput(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    timezone: str
    first_date: date
    event_time: wall_time
    opening_days_before: int = Field(ge=0, le=32)
    opening_time: wall_time
    closing_days_before: int = Field(ge=0, le=32)
    closing_time: wall_time
    tables: list[TableInput] = Field(min_length=1, max_length=10)
    skip_dates: list[date] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def validate_rule(self) -> "ScheduleInput":
        EventInput.valid_zone(self.timezone)
        if not self.title.strip() or len(
            {t.name.casefold() for t in self.tables}
        ) != len(self.tables):
            raise ValueError("Title and unique table names are required")
        for clock in (self.event_time, self.opening_time, self.closing_time):
            if clock.tzinfo is not None or clock.second or clock.microsecond:
                raise ValueError("Use local times with minute precision")
        return self


def preview(body: ScheduleInput, now: float | None = None) -> list[dict[str, Any]]:
    now = time.time() if now is None else now
    today = datetime.fromtimestamp(now, ZoneInfo(body.timezone)).date()
    day = body.first_date
    if day < today:
        day += timedelta(weeks=math.ceil((today - day).days / 7))
    rows: list[dict[str, Any]] = []
    for week in range(8):
        event_day = day + timedelta(weeks=week)
        row: dict[str, Any] = {
            "date": event_day.isoformat(),
            "skipped": event_day in body.skip_dates,
        }
        try:
            start = resolve_local(event_day, body.event_time, body.timezone)
            opening = resolve_local(
                event_day - timedelta(days=body.opening_days_before),
                body.opening_time,
                body.timezone,
            )
            closing = resolve_local(
                event_day - timedelta(days=body.closing_days_before),
                body.closing_time,
                body.timezone,
            )
            if not opening < closing < start or closing - opening > 768 * 3600:
                raise ValueError(
                    "Require opening < closing < event start; maximum window is 32 days"
                )
            row.update(starts_at=start, opens_at=opening, signup_closes_at=closing)
            if opening <= now and not row["skipped"]:
                raise ValueError(
                    "Opening has passed; skip this date or choose a later first date"
                )
        except ValueError as error:
            row["error"] = str(error)
        rows.append(row)
    return rows


def schedule_data(schedule: Schedule) -> dict[str, Any]:
    return {
        "id": schedule.id,
        "title": schedule.title,
        "timezone": schedule.timezone,
        "tables": schedule.tables,
        "active": schedule.active,
        "revision": schedule.revision,
        "last_error": schedule.last_error,
        **schedule.rule,
    }


def materialize(db: Session, schedule: Schedule, now: float | None = None) -> None:
    body = ScheduleInput.model_validate(schedule_data(schedule))
    rows = preview(body, now)
    existing = set(
        db.scalars(
            select(Event.occurrence_date).where(Event.schedule_id == schedule.id)
        )
    )
    errors = []
    for row in rows:
        if row["date"] in existing or row["skipped"]:
            continue
        if row.get("error"):
            errors.append(f"{row['date']}: {row['error']}")
            continue
        db.add(
            Event(
                id=str(uuid.uuid4()),
                guild_id=schedule.guild_id,
                title=schedule.title,
                timezone=schedule.timezone,
                schedule_id=schedule.id,
                occurrence_date=row["date"],
                starts_at=row["starts_at"],
                opens_at=row["opens_at"],
                signup_closes_at=row["signup_closes_at"],
                duration_hours=math.ceil(
                    (row["signup_closes_at"] - row["opens_at"]) / 3600
                ),
                tables=[dict(t) for t in schedule.tables],
                status="scheduled",
                created_by=schedule.created_by,
            )
        )
    schedule.last_error = "; ".join(errors)[:500] or None
    db.flush()


def replenish(engine: Engine, guild_id: str) -> None:
    with Session(engine) as db:
        ids = list(
            db.scalars(
                select(Schedule.id).where(
                    Schedule.guild_id == guild_id, Schedule.active.is_(True)
                )
            )
        )
    for schedule_id in ids:
        with Session(engine) as db:
            schedule = db.scalar(
                select(Schedule)
                .where(Schedule.id == schedule_id, Schedule.active.is_(True))
                .with_for_update()
            )
            if schedule is None:
                continue
            try:
                materialize(db, schedule)
                db.commit()
            except IntegrityError:
                db.rollback()
