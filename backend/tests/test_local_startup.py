from sqlalchemy import inspect

from app.main import create_app


def test_local_api_reload_applies_pending_sqlite_migrations(tmp_path, monkeypatch):
    monkeypatch.setenv("TABLESIGNUP_LOCAL_AUTO_MIGRATE", "1")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/local.db")
    app = create_app()
    assert inspect(app.state.engine).has_table("event_templates")
    app.state.engine.dispose()
