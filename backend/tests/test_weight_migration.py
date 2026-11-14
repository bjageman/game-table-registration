from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, text
from sqlalchemy.orm import Session

from app.models import EventPlayerSetting, PlayerProfile


def test_weight_reset_migration_runs_once_and_preserves_profile_fields(
    tmp_path, monkeypatch
):
    url = f"sqlite:///{tmp_path}/migration.db"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "20261101_archive_events")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text("""
            INSERT INTO player_profiles
            (guild_id, discord_id, discord_name, real_name,
             weighting, is_test, guaranteed_seat)
            VALUES ('guild', '123', 'Discord Name', 'Saved Display', 3.5, 0, 1),
                   ('other', 'test-123', 'Test Player', 'Test Display', 0.25, 1, 0)
        """)
        )
    command.upgrade(config, "head")
    with engine.begin() as connection:
        rows = connection.execute(
            text(
                "SELECT real_name, weighting, is_test, guaranteed_seat "
                "FROM player_profiles ORDER BY guild_id"
            )
        ).all()
        assert rows == [("Saved Display", 5.0, 0, 1), ("Test Display", 5.0, 1, 0)]
        connection.execute(text("UPDATE player_profiles SET weighting = 1.1"))
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert set(
            connection.execute(text("SELECT weighting FROM player_profiles")).scalars()
        ) == {1.1}
    engine.dispose()


def test_five_point_scale_migration_preserves_history_and_runs_once(
    tmp_path, monkeypatch
):
    url = f"sqlite:///{tmp_path}/scale.db"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "20261105_public_event_sharing")
    engine = create_engine(url)
    # Seed the historical schema without using today's Event model, which may
    # contain columns introduced after the revision being tested.
    events = Table("events", MetaData(), autoload_with=engine)
    profiles = Table("player_profiles", MetaData(), autoload_with=engine)
    with Session(engine) as db:
        db.execute(
            events.insert().values(
                id="event",
                guild_id="guild",
                title="Event",
                starts_at=2000000000,
                duration_hours=24,
                tables=[],
                status="draft",
                created_by="owner",
            )
        )
        for pid, weight in (("seated", 0.9), ("waiting", 1.1), ("custom", 3)):
            db.execute(
                profiles.insert().values(
                    guild_id="guild",
                    discord_id=pid,
                    discord_name=pid,
                    weighting=weight,
                    real_name="",
                    is_test=False,
                    guaranteed_seat=False,
                )
            )
        db.commit()
        db.add(EventPlayerSetting(event_id="event", discord_id="custom", weighting=1.2))
        db.commit()
    command.upgrade(config, "head")
    with Session(engine) as db:
        assert {p.discord_id: p.weighting for p in db.query(PlayerProfile)} == {
            "seated": 4.5,
            "waiting": 5.5,
            "custom": 10,
        }
        assert db.get(EventPlayerSetting, ("event", "custom")).weighting == 6
        db.get(PlayerProfile, ("user:owner", "guild", "waiting")).weighting = 6
        db.commit()
    command.upgrade(config, "head")
    with Session(engine) as db:
        assert db.get(PlayerProfile, ("user:owner", "guild", "waiting")).weighting == 6
    engine.dispose()
