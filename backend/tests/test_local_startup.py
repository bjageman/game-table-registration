from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.main import create_app
from app.models import Base


def test_local_api_reload_applies_pending_sqlite_migrations(tmp_path, monkeypatch):
    monkeypatch.setenv("TABLESIGNUP_LOCAL_AUTO_MIGRATE", "1")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/local.db")
    app = create_app()
    assert inspect(app.state.engine).has_table("event_templates")
    app.state.engine.dispose()


def test_local_upgrade_resumes_after_partial_sqlite_ddl(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path}/partial.db"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "20261102_event_manager_signups")
    engine = create_engine(url)
    for name in (
        "user_identities",
        "organizations",
        "organization_members",
        "organization_selections",
    ):
        Base.metadata.tables[name].create(engine)
    with engine.begin() as db:
        db.execute(text("ALTER TABLE events ADD COLUMN organization_id VARCHAR(36)"))
    command.upgrade(Config("alembic.ini"), "head")
    assert {index["name"] for index in inspect(engine).get_indexes("events")} >= {
        "ix_events_organization_id"
    }
    engine.dispose()


def test_timezone_migration_preserves_existing_preferences(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path}/timezone.db"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "20261105_event_update_threads")
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(
            text(
                "INSERT INTO assignment_preferences (scope_key, "
                "automatic_weight_adjustment, announce_table_changes, "
                "post_discord_updates_to_thread) VALUES ('user:owner', 0, 1, 1)"
            )
        )
    command.upgrade(config, "head")
    with engine.connect() as db:
        row = db.execute(
            text(
                "SELECT automatic_weight_adjustment, announce_table_changes, "
                "post_discord_updates_to_thread, timezone "
                "FROM assignment_preferences WHERE scope_key = 'user:owner'"
            )
        ).one()
        assert tuple(row) == (0, 1, 1, None)
    command.downgrade(config, "20261105_event_update_threads")
    assert "timezone" not in {
        column["name"]
        for column in inspect(engine).get_columns("assignment_preferences")
    }
    engine.dispose()
