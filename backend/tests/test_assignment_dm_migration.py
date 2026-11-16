"""New preferences preserve historical notices and explicit player choices."""

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.models import AssignmentPreference, Event, PlayerProfile, PromotionDM


def test_assignment_dm_settings_upgrade_and_rollback(tmp_path):
    config = Config("alembic.ini")
    url = f"sqlite:///{tmp_path}/assignment-dms.db"
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    engine = create_engine(url)
    with Session(engine) as db:
        db.add(
            Event(
                id="event",
                guild_id="guild",
                title="Games",
                starts_at=1,
                duration_hours=24,
                tables=[],
                created_by="owner",
            )
        )
        db.add(
            AssignmentPreference(scope_key="user:owner", dm_waitlist_promotions=False)
        )
        db.add(PlayerProfile(scope_key="user:owner", guild_id="guild", discord_id="1"))
        db.flush()
        db.add(
            PromotionDM(
                id="old-notice",
                event_id="event",
                discord_id="1",
                table_name="A",
                payload={"content": "Historical notice"},
                created_at=1,
                next_attempt=1,
            )
        )
        db.commit()
    command.downgrade(config, "20261120_seat_order")
    assert "kind" not in {
        c["name"] for c in inspect(engine).get_columns("promotion_dms")
    }
    command.upgrade(config, "head")
    command.check(config)
    with Session(engine) as db:
        prefs = db.get(AssignmentPreference, "user:owner")
        assert prefs.dm_assignments is True
        assert prefs.dm_waitlist_promotions is False
        assert (
            db.get(PlayerProfile, ("user:owner", "guild", "1")).seat_notifications
            is True
        )
        notice = db.get(PromotionDM, "old-notice")
        assert notice.kind == "promotion"
        assert notice.payload == {"content": "Historical notice"}
    engine.dispose()
