"""Upgrade existing schedules without changing their publication state."""

from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, select


def test_existing_published_occurrences_detach_with_provenance(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path}/schedules.db"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "20261114_signup_warnings")
    engine = create_engine(url)
    metadata = MetaData()
    series = Table("recurring_series", metadata, autoload_with=engine)
    events = Table("events", metadata, autoload_with=engine)
    with engine.begin() as db:
        db.execute(
            series.insert().values(
                id="series",
                created_by="owner",
                guild_id="guild",
                channel_id="channel",
                title="Game night",
                description="",
                location="Game Store",
                tables=[],
                first_local="2030-01-01T18:00",
                time_zone="UTC",
                frequency="weekly",
                opens_before_hours=72,
                closes_before_hours=24,
                active=True,
            )
        )
        for index, status in enumerate(("open", "scheduled")):
            db.execute(
                events.insert().values(
                    id=status,
                    guild_id="guild",
                    channel_id="channel",
                    title="Game night",
                    starts_at=1900000000 + index * 604800,
                    duration_hours=48,
                    tables=[],
                    status=status,
                    created_by="owner",
                    series_id="series",
                    description="",
                    location="Game Store",
                    signup_mode="poll",
                    published_at=1800000000 if status == "open" else None,
                    message_id="message" if status == "open" else None,
                )
            )
    command.upgrade(config, "head")
    command.check(config)
    events = Table("events", MetaData(), autoload_with=engine)
    with engine.connect() as db:
        rows = {row.id: row for row in db.execute(select(events))}
        assert rows["open"].series_id is None
        assert rows["scheduled"].series_id == "series"
        for row in rows.values():
            assert row.source_series_id == "series"
            assert row.series_slot_at == row.starts_at
    command.downgrade(config, "20261114_signup_warnings")
    command.upgrade(config, "head")
    command.check(config)
    engine.dispose()
