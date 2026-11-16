"""Existing draws retain their original order through upgrade and rollback."""

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.models import Event, LotteryRun


def test_seat_order_migration_preserves_existing_draws(tmp_path):
    url = f"sqlite:///{tmp_path}/seat-order.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    engine = create_engine(url)
    snapshot = {"players": [{"id": "1", "name": "Alice"}]}
    result = {
        "assignments": {"1": "A"},
        "waitlist": [],
        "tables": [
            {"name": "A", "players": snapshot["players"], "waitlist": []},
        ],
    }
    with Session(engine) as db:
        db.add(
            Event(
                id="event",
                guild_id="guild",
                title="Games",
                starts_at=1,
                duration_hours=24,
                tables=[{"name": "A", "capacity": 1}],
                created_by="owner",
            )
        )
        db.flush()
        db.add(
            LotteryRun(
                event_id="event",
                version="test",
                seed="seed",
                snapshot=snapshot,
                result=result,
                created_by="owner",
                created_at=1,
            )
        )
        db.commit()
    command.downgrade(config, "20261119_player_swaps")
    assert "seat_order" not in {
        c["name"] for c in inspect(engine).get_columns("lottery_runs")
    }
    command.upgrade(config, "head")
    command.check(config)
    with Session(engine) as db:
        run = db.get(LotteryRun, "event")
        assert run.seat_order == {}
        assert run.snapshot == snapshot
        assert run.result == result
    engine.dispose()
