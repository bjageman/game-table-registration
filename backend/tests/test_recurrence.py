from datetime import datetime
from zoneinfo import ZoneInfo

from app.events.recurrence import occurrence
from app.models import RecurringSeries


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
