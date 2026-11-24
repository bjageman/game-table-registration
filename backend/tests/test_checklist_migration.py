"""Existing events start with an empty shared checklist after upgrading."""

from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, inspect, select


def test_public_checklist_migration_preserves_existing_events(tmp_path):
    url = f"sqlite:///{tmp_path}/checklist-migration.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "20261123_short_notice")
    engine = create_engine(url)
    events = Table("events", MetaData(), autoload_with=engine)
    with engine.begin() as connection:
        connection.execute(
            events.insert().values(
                id="saved",
                guild_id="guild",
                title="Existing game",
                starts_at=2000000000,
                duration_hours=24,
                tables=[],
                status="assigned",
                created_by="owner",
            )
        )
    command.upgrade(config, "head")
    events = Table("events", MetaData(), autoload_with=engine)
    with engine.connect() as connection:
        event = connection.execute(select(events)).mappings().one()
        assert event["title"] == "Existing game"
        assert event["public_checklist"] == {}
        assert event["public_checklist_revision"] == 0
    command.downgrade(config, "20261123_short_notice")
    assert "public_checklist" not in {
        col["name"] for col in inspect(engine).get_columns("events")
    }
    engine.dispose()
