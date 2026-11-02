from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_custom_signup_migration_preserves_existing_polls_and_rolls_back(
    tmp_path, monkeypatch
):
    url = f"sqlite:///{tmp_path}/signup-migration.db"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "20261101_connect_callback")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text("""
            INSERT INTO events
            (id, guild_id, channel_id, title, starts_at, duration_hours,
             tables, status, created_by, message_id, answers)
            VALUES ('legacy', 'guild', 'channel', 'Existing event', 4000000000, 24,
                    '[]', 'open', 'owner', 'message', '[{"answer_id": 9}]')
            """)
        )
    command.upgrade(config, "head")
    command.check(config)
    with engine.begin() as connection:
        assert connection.execute(
            text("SELECT signup_mode, message_id, answers FROM events")
        ).one() == ("poll", "message", '[{"answer_id": 9}]')
        connection.execute(
            text("""
            INSERT INTO table_signups (event_id, discord_id, discord_name, choices)
            VALUES ('legacy', '1', 'Player', '["A"]')
            """)
        )
    command.downgrade(config, "20261101_connect_callback")
    assert "table_signups" not in inspect(engine).get_table_names()
    assert "signup_interactions" not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT message_id FROM events")).scalar()
            == "message"
        )
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    command.check(config)
    engine.dispose()
