from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Base, Event, RecurringSeries
from app.recurrence import fill_schedule, occurrence


def series(first: str, frequency: str) -> RecurringSeries:
    return RecurringSeries(
        first_local=first,
        frequency=frequency,
        time_zone="America/New_York",
    )


def test_weekly_recurrence_keeps_local_time_across_daylight_saving():
    schedule = series("2026-10-26T18:00", "weekly")
    first = datetime.fromtimestamp(
        occurrence(schedule, 0), ZoneInfo(schedule.time_zone)
    )
    second = datetime.fromtimestamp(
        occurrence(schedule, 1), ZoneInfo(schedule.time_zone)
    )
    assert (first.hour, second.hour) == (18, 18)
    assert (second.timestamp() - first.timestamp()) == 7 * 86400 + 3600


def test_monthly_recurrence_skips_months_without_the_day():
    schedule = series("2026-01-31T18:00", "monthly")
    assert occurrence(schedule, 1) is None
    march = datetime.fromtimestamp(
        occurrence(schedule, 2), ZoneInfo(schedule.time_zone)
    )
    assert (march.month, march.day, march.hour) == (3, 31, 18)


def test_nonexistent_spring_wall_time_is_skipped():
    schedule = series("2026-03-07T02:30", "daily")
    assert occurrence(schedule, 1) is None
    assert occurrence(schedule, 2) is not None


def test_fill_schedule_does_not_recreate_an_archived_occurrence():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    now = datetime(2026, 12, 1, tzinfo=ZoneInfo("America/New_York")).timestamp()
    with Session(engine) as db:
        schedule = RecurringSeries(
            id="series",
            created_by="user",
            guild_id="guild",
            channel_id="channel",
            title="Weekly game",
            description="",
            location="",
            tables=[{"name": "One", "capacity": 15}],
            first_local="2027-01-04T18:00",
            time_zone="America/New_York",
            frequency="weekly",
            opens_before_hours=72,
            closes_before_hours=24,
            active=True,
        )
        db.add(schedule)
        start = occurrence(schedule, 0)
        assert start is not None
        db.add(
            Event(
                id="archived",
                series_id=schedule.id,
                guild_id=schedule.guild_id,
                channel_id=schedule.channel_id,
                title=schedule.title,
                starts_at=start,
                duration_hours=48,
                tables=schedule.tables,
                status="assigned",
                created_by=schedule.created_by,
                archived_at=now,
            )
        )
        db.flush()

        fill_schedule(db, schedule, now)
        db.commit()

        starts = list(
            db.scalars(select(Event.starts_at).where(Event.series_id == schedule.id))
        )
        assert len(starts) == 5
        assert len(set(starts)) == 5
