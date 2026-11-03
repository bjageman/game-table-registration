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
