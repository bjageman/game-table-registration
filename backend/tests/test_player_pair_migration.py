from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.models import PlayerProfile


def test_migration_copies_shared_profiles_into_independent_organization_records(
    tmp_path, monkeypatch
):
    url = f"sqlite:///{tmp_path}/pairs.db"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "20261113_assignment_review")
    engine = create_engine(url)
    with engine.begin() as db:
        for org in ("a", "b"):
            db.execute(
                text(
                    "INSERT INTO organizations "
                    "(id, name, normalized_name, created_by, guild_id, channel_id) "
                    "VALUES (:id, :id, :id, 'owner', 'guild', 'channel')"
                ),
                {"id": org},
            )
        db.execute(
            text(
                "INSERT INTO player_profiles (guild_id, discord_id, discord_name, "
                "real_name, weighting, is_test, guaranteed_seat) "
                "VALUES ('guild', '1', 'Alice', 'Saved name', 8, 0, 1)"
            )
        )
    command.upgrade(config, "head")
    command.check(config)
    with Session(engine) as db:
        a = db.get(PlayerProfile, ("org:a", "guild", "1"))
        b = db.get(PlayerProfile, ("org:b", "guild", "1"))
        assert a is not b
        assert a.weighting == b.weighting == 8
        a.weighting = 2
        a.real_name = "Only organization A"
        db.commit()
        assert b.weighting == 8
        assert b.real_name == "Saved name"
        assert a.partner_id is b.partner_id is None
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    command.check(config)
    engine.dispose()
