"""Waitlist guarantees default off without changing existing manual guarantees."""

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.models import AssignmentPreference, PlayerProfile


def test_waitlist_guarantee_migration_preserves_profiles_and_defaults(tmp_path):
    config = Config("alembic.ini")
    url = f"sqlite:///{tmp_path}/guarantees.db"
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    engine = create_engine(url)
    with Session(engine) as db:
        db.add(AssignmentPreference(scope_key="user:owner", dm_assignments=False))
        db.add(
            PlayerProfile(
                scope_key="user:owner",
                guild_id="guild",
                discord_id="1",
                guaranteed_seat=True,
            )
        )
        db.commit()
    command.downgrade(config, "20261121_assignment_dms")
    assert "guarantee_waitlisted_players" not in {
        c["name"] for c in inspect(engine).get_columns("assignment_preferences")
    }
    command.upgrade(config, "head")
    command.check(config)
    with Session(engine) as db:
        preferences = db.get(AssignmentPreference, "user:owner")
        assert preferences.guarantee_waitlisted_players is False
        assert preferences.waitlist_guarantee_retention_hours == 5
        assert preferences.dm_assignments is False
        assert (
            db.get(PlayerProfile, ("user:owner", "guild", "1")).guaranteed_seat is True
        )
    engine.dispose()


def test_short_notice_checkbox_preserves_legacy_disabled_window(tmp_path):
    from sqlalchemy import text

    config = Config("alembic.ini")
    url = f"sqlite:///{tmp_path}/short-notice.db"
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "20261122_waitlist_guarantees")
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(
            text(
                "INSERT INTO assignment_preferences "
                "(scope_key, waitlist_guarantee_retention_hours) "
                "VALUES ('user:owner', 0)"
            )
        )
    command.upgrade(config, "head")
    command.check(config)
    with Session(engine) as db:
        preferences = db.get(AssignmentPreference, "user:owner")
        assert preferences.keep_waitlist_guarantee_on_short_notice is False
        assert preferences.waitlist_guarantee_retention_hours == 5
        preferences.waitlist_guarantee_retention_hours = 3
        db.commit()
    command.downgrade(config, "20261122_waitlist_guarantees")
    with engine.connect() as db:
        assert (
            db.execute(
                text(
                    "SELECT waitlist_guarantee_retention_hours "
                    "FROM assignment_preferences"
                )
            ).scalar_one()
            == 0
        )
    engine.dispose()
