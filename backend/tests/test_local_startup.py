import os
import uuid

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.main import create_app
from app.models import Base


def test_local_api_reload_applies_pending_sqlite_migrations(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path}/local.db"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "20261112_general_timezone")
    app = create_app()
    with TestClient(app):
        assert inspect(app.state.engine).has_table("event_templates")
        assert "signup_roster_messages" in {
            column["name"] for column in inspect(app.state.engine).get_columns("events")
        }
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


def test_open_roster_migration_preserves_timezone_and_defaults_off(
    tmp_path, monkeypatch
):
    url = f"sqlite:///{tmp_path}/open-rosters.db"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "20261112_general_timezone")
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(
            text(
                "INSERT INTO assignment_preferences (scope_key, timezone) "
                "VALUES ('user:owner', 'America/New_York')"
            )
        )
        db.execute(
            text(
                "INSERT INTO events (id, guild_id, title, starts_at, duration_hours, "
                "tables, status, created_by, message_id, signup_mode) "
                "VALUES ('open-event', 'guild', 'Game Night', 2000000000, 24, "
                "'[]', 'open', 'owner', 'message', 'reactions')"
            )
        )
    command.upgrade(config, "head")
    with engine.connect() as db:
        row = db.execute(
            text(
                "SELECT timezone, show_open_signup_players "
                "FROM assignment_preferences WHERE scope_key = 'user:owner'"
            )
        ).one()
        assert tuple(row) == ("America/New_York", 0)
        assert (
            db.execute(
                text("SELECT signup_roster_hash FROM events WHERE id = 'open-event'")
            ).scalar_one()
            == "restore"
        )
    assert {
        "signup_roster_hash",
        "signup_roster_checked_at",
        "signup_roster_messages",
    } <= {column["name"] for column in inspect(engine).get_columns("events")}
    command.downgrade(config, "20261112_general_timezone")
    with engine.connect() as db:
        assert (
            db.execute(
                text(
                    "SELECT timezone FROM assignment_preferences "
                    "WHERE scope_key = 'user:owner'"
                )
            ).scalar_one()
            == "America/New_York"
        )
    engine.dispose()


def test_postgres_migration_revision_fits_and_rolls_back():
    database_url = os.environ.get("TEST_DATABASE_URL", "")
    if not database_url.startswith("postgresql"):
        pytest.skip("TEST_DATABASE_URL must point to PostgreSQL")
    schema = f"migration_test_{uuid.uuid4().hex}"
    engine = create_engine(database_url)
    isolated_url = make_url(database_url).update_query_dict(
        {"options": f"-csearch_path={schema}"}
    )
    config = Config("alembic.ini")
    config.set_main_option(
        "sqlalchemy.url",
        isolated_url.render_as_string(hide_password=False).replace("%", "%%"),
    )
    try:
        with engine.begin() as db:
            db.execute(text(f'CREATE SCHEMA "{schema}"'))
        command.upgrade(config, "head")
        with engine.connect() as db:
            version_column = next(
                column
                for column in inspect(db).get_columns("alembic_version", schema=schema)
                if column["name"] == "version_num"
            )
            revision = db.execute(
                text(f'SELECT version_num FROM "{schema}".alembic_version')
            ).scalar_one()
            assert len(revision) <= version_column["type"].length
        command.upgrade(config, "head")
        command.check(config)
        command.downgrade(config, "base")
        command.upgrade(config, "head")
    finally:
        with engine.begin() as db:
            db.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()
