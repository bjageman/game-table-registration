from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.models import PlayerPairing, PlayerProfile


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
        assert db.query(PlayerPairing).count() == 0
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    command.check(config)
    engine.dispose()


def test_preferences_migrate_existing_reciprocal_pairs_and_round_trip(
    tmp_path, monkeypatch
):
    url = f"sqlite:///{tmp_path}/preferences.db"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "20261123_short_notice")
    engine = create_engine(url)
    with engine.begin() as db:
        for scope in ("org:a", "org:b"):
            for pid, partner in (("1", "2"), ("2", "1"), ("3", "4"), ("4", None)):
                db.execute(
                    text(
                        "INSERT INTO player_profiles "
                        "(scope_key, guild_id, discord_id, discord_name, "
                        "real_name, weighting, is_test, guaranteed_seat, partner_id) "
                        "VALUES (:scope, 'guild', :pid, :pid, '', 5, 0, 0, :partner)"
                    ),
                    {"scope": scope, "pid": pid, "partner": partner},
                )
    command.upgrade(config, "head")
    command.check(config)
    with Session(engine) as db:
        edges = db.query(PlayerPairing).all()
        assert {(e.scope_key, e.player_id, e.preferred_id) for e in edges} == {
            ("org:a", "1", "2"),
            ("org:b", "1", "2"),
        }
        # Multi-preference downgrade keeps one reciprocal pair deterministically.
        db.add(
            PlayerPairing(
                scope_key="org:a", guild_id="guild", player_id="1", preferred_id="3"
            )
        )
        db.commit()
    command.downgrade(config, "20261123_short_notice")
    with engine.connect() as db:
        rows = db.execute(
            text(
                "SELECT discord_id, partner_id FROM player_profiles "
                "WHERE scope_key = 'org:a'"
            )
        ).all()
        assert dict(rows) == {"1": "2", "2": "1", "3": None, "4": None}
    command.upgrade(config, "head")
    command.check(config)
    engine.dispose()
