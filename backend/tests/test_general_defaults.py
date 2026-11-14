"""New scopes enable every General option before their first settings save."""

from flow_helpers import login
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.assignment_preferences import DEFAULTS, for_event
from app.event_threads import enabled as threads_enabled
from app.models import AssignmentPreference, Event, PromotionDM
from app.withdrawals import manager_remove


def test_new_user_and_organization_defaults_and_explicit_opt_outs(client):
    headers = login(client)
    expected = {**DEFAULTS, "timezone": None}
    assert client.get("/api/settings/assignment").json() == expected
    disabled = {key: False for key in DEFAULTS}
    assert client.put(
        "/api/settings/assignment", headers=headers, json=disabled
    ).json() == {**disabled, "timezone": None}
    # Older clients must preserve all omitted saved choices.
    client.put(
        "/api/settings/assignment",
        headers=headers,
        json={"automatic_weight_adjustment": False, "announce_table_changes": False},
    )
    assert client.get("/api/settings/assignment").json() == {
        **disabled,
        "timezone": None,
    }
    org = client.post(
        "/api/organizations", headers=headers, json={"name": "Fresh defaults"}
    ).json()
    client.put(
        "/api/organizations/selection",
        headers=headers,
        json={"organization_id": org["id"]},
    )
    assert client.get("/api/settings/assignment").json() == expected
    # A first save by an older client uses enabled defaults for omitted fields.
    saved = client.put(
        "/api/settings/assignment",
        headers=headers,
        json={"automatic_weight_adjustment": True, "announce_table_changes": True},
    ).json()
    assert saved == expected
    client.put(
        "/api/organizations/selection", headers=headers, json={"organization_id": None}
    )
    assert client.get("/api/settings/assignment").json() == {
        **disabled,
        "timezone": None,
    }


def test_background_behavior_uses_defaults_without_a_saved_row(promotion_db):
    engine = promotion_db
    with Session(engine) as db:
        db.execute(delete(AssignmentPreference))
        db.commit()
        event = db.get(Event, "event")
        preferences = for_event(db, event)
        assert all(getattr(preferences, key) is True for key in DEFAULTS)
        assert threads_enabled(db, event)
        assert db.get(AssignmentPreference, "user:owner") is None
    assert manager_remove(engine, "guild", "event", "1")
    with Session(engine) as db:
        assert db.scalar(select(PromotionDM.discord_id)) == "2"
        preference = AssignmentPreference(scope_key="user:new")
        db.add(preference)
        db.flush()
        assert all(getattr(preference, key) is True for key in DEFAULTS)


def test_defaults_migration_preserves_saved_false_and_sets_sql_defaults(tmp_path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    migration = Config("alembic.ini")
    url = f"sqlite:///{tmp_path}/defaults.db"
    migration.set_main_option("sqlalchemy.url", url)
    command.upgrade(migration, "20261113_waitlist_additions")
    engine = create_engine(url)
    columns = ", ".join(
        key for key in DEFAULTS if key != "review_assignments_before_discord"
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO assignment_preferences (scope_key, {columns}) "
                "VALUES ('user:existing', 0, 0, 0, 0, 0)"
            )
        )
    command.upgrade(migration, "head")
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO assignment_preferences (scope_key) VALUES ('org:fresh')")
        )
        assert tuple(
            connection.execute(
                text(
                    f"SELECT {columns} FROM assignment_preferences "
                    "WHERE scope_key='org:fresh'"
                )
            ).one()
        ) == (1, 1, 1, 1, 1)
        assert tuple(
            connection.execute(
                text(
                    f"SELECT {columns} FROM assignment_preferences "
                    "WHERE scope_key='user:existing'"
                )
            ).one()
        ) == (0, 0, 0, 0, 0)
    command.downgrade(migration, "20261113_waitlist_additions")
    command.upgrade(migration, "head")
    engine.dispose()
