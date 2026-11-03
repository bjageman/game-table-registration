from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


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
        assert rows == [("Saved Display", 1.0, 0, 1), ("Test Display", 1.0, 1, 0)]
        connection.execute(text("UPDATE player_profiles SET weighting = 1.1"))
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert set(
            connection.execute(text("SELECT weighting FROM player_profiles")).scalars()
        ) == {1.1}
    engine.dispose()
