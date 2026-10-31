from datetime import date, time

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Base, Event, Schedule
from app.scheduling import ScheduleInput, materialize, preview, resolve_local


def rule(**patch):
    return ScheduleInput.model_validate(
        {
            "title": "Friday",
            "timezone": "America/New_York",
            "first_date": "2090-06-16",
            "event_time": "19:00",
            "opening_days_before": 7,
            "opening_time": "12:00",
            "closing_days_before": 1,
            "closing_time": "12:00",
            "tables": [{"name": "A", "capacity": 15}],
            **patch,
        }
    )


def test_dst_gaps_and_folds():
    for day in [date(2090, 3, 12), date(2090, 11, 5)]:
        with pytest.raises(ValueError, match="missing or ambiguous"):
            resolve_local(
                day, time(2, 30) if day.month == 3 else time(1, 30), "America/New_York"
            )
    assert resolve_local(date(2090, 3, 13), time(2, 30), "America/New_York") > 0


def test_weekly_preview_and_unique_materialization():
    body = rule()
    rows = preview(body)
    assert len(rows) == 8
    assert all(not r.get("error") for r in rows)
    assert rows[0]["opens_at"] < rows[0]["signup_closes_at"] < rows[0]["starts_at"]
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        schedule = Schedule(
            id="schedule",
            guild_id="guild",
            title=body.title,
            timezone=body.timezone,
            rule=body.model_dump(mode="json", exclude={"title", "timezone", "tables"}),
            tables=[t.model_dump() for t in body.tables],
            active=True,
            created_by="owner",
        )
        db.add(schedule)
        db.flush()
        materialize(db, schedule)
        materialize(db, schedule)
        db.commit()
        events = list(db.scalars(select(Event)))
        assert len(events) == 8
        assert all(e.status == "scheduled" for e in events)
        assert events[0].tables == [{"name": "A", "capacity": 15}]


def test_preview_reports_dst_and_explicit_skips():
    body = rule(first_date="2090-03-12", event_time="02:30")
    rows = preview(body)
    assert "ambiguous" in rows[0]["error"]
    assert preview(
        rule(first_date="2090-03-12", event_time="02:30", skip_dates=["2090-03-12"])
    )[0]["skipped"]


def test_weekly_wall_times_follow_dst_offset_change():
    rows = preview(
        rule(
            first_date="2090-03-05",
            opening_days_before=0,
            opening_time="12:00",
            closing_days_before=0,
            closing_time="18:00",
        )
    )
    assert rows[1]["starts_at"] - rows[0]["starts_at"] == 167 * 3600
    assert all(not row.get("error") for row in rows)
