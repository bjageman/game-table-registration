"""Table edits must persist through removal, reload, and adding again."""

import pytest
from sqlalchemy.orm import Session

from app.assignments.withdrawals import current_result
from app.events.player_edits import edit_player
from app.events.signups import apply_manager_players, apply_manager_signups
from app.events.test_signups import add_to_rows
from app.models import Event, LotteryRun, PlayerProfile, TableSignup


@pytest.mark.parametrize("status", ["draft", "scheduled", "open"])
def test_remove_then_add_only_restores_selected_table(promotion_db, status):
    engine = promotion_db
    pid = "test-" + "a" * 24
    with Session(engine) as db:
        event = db.get(Event, "event")
        event.status = status
        event.tables = [{"name": name, "capacity": 8} for name in ("A", "B", "C")]
        event.test_signups = {
            "players": [
                {"id": pid, "name": "Test Player 003", "choices": ["A", "B", "C"]}
            ]
        }
        db.add(
            PlayerProfile(
                scope_key="user:owner",
                guild_id="guild",
                discord_id=pid,
                discord_name="Test Player 003",
                is_test=True,
            )
        )
        db.add(
            TableSignup(
                event_id="event",
                discord_id=pid,
                discord_name="Test Player 003",
                choices=["A", "B", "C"],
            )
        )
        db.commit()
    for table in ("A", "B"):
        edit_player(engine, "guild", "event", pid, table, adding=False)
    with Session(engine) as db:
        event = db.get(Event, "event")
        assert event.test_signups["players"][0]["choices"] == ["C"]
        assert db.get(TableSignup, ("event", pid)).choices == ["C"]
    edit_player(engine, "guild", "event", pid, "A", adding=True, name="Test Player 003")
    with Session(engine) as db:
        event = db.get(Event, "event")
        rows = apply_manager_signups(
            db,
            event,
            add_to_rows(
                [{"name": name, "players": []} for name in ("A", "B", "C")],
                event.test_signups,
            ),
        )
        assert [row["name"] for row in rows if row["players"]] == ["A", "C"]
        players = apply_manager_players(db, event, event.test_signups["players"])
        assert set(players[0]["choices"]) == {"A", "C"}


@pytest.mark.parametrize("status", ["review", "assigned"])
def test_waitlist_removal_is_scoped_and_can_be_restored(promotion_db, status):
    engine = promotion_db
    with Session(engine) as db:
        event = db.get(Event, "event")
        event.status = status
        event.tables = [*event.tables, {"name": "Table B", "capacity": 1}]
        run = db.get(LotteryRun, "event")
        run.result = {
            **run.result,
            "tables": [
                *run.result["tables"],
                {
                    "name": "Table B",
                    "players": [],
                    "waitlist": [{"id": "2", "name": "Bob"}],
                },
            ],
        }
        db.commit()
    edit_player(engine, "guild", "event", "2", "Table A", adding=False, waitlist=True)
    with Session(engine) as db:
        result = current_result(db, db.get(LotteryRun, "event"))
        assert [p["id"] for p in result["tables"][0]["waitlist"]] == ["3"]
        assert [p["id"] for p in result["tables"][1]["waitlist"]] == ["2"]
    edit_player(engine, "guild", "event", "2", "Table A", adding=True, waitlist=True)
    with Session(engine) as db:
        result = current_result(db, db.get(LotteryRun, "event"))
        assert [p["id"] for p in result["tables"][0]["waitlist"]] == ["3", "2"]
        assert "2" in {p["id"] for p in result["tables"][1]["waitlist"]}


def test_adding_after_legacy_removal_does_not_revive_generated_choices(promotion_db):
    from app.models import EventManagerSignup

    pid = "test-" + "b" * 24
    with Session(promotion_db) as db:
        event = db.get(Event, "event")
        event.status = "draft"
        event.tables = [{"name": name, "capacity": 8} for name in ("A", "B")]
        event.test_signups = {
            "players": [{"id": pid, "name": "Test Player 003", "choices": ["A", "B"]}]
        }
        db.add(
            PlayerProfile(
                scope_key="user:owner",
                guild_id="guild",
                discord_id=pid,
                discord_name="Test Player 003",
                is_test=True,
            )
        )
        db.add(
            EventManagerSignup(
                event_id="event",
                discord_id=pid,
                discord_name="Test Player 003",
                removed=True,
                choices=[],
            )
        )
        db.commit()
    edit_player(
        promotion_db, "guild", "event", pid, "A", adding=True, name="Test Player 003"
    )
    with Session(promotion_db) as db:
        event = db.get(Event, "event")
        assert event.test_signups["players"][0]["choices"] == []
        players = apply_manager_players(db, event, event.test_signups["players"])
        assert players[0]["choices"] == ["A"]


@pytest.mark.parametrize("mode", ["poll", "reactions"])
def test_guarantee_uses_the_same_roster_as_the_table_view(client, mode):
    from flow_helpers import event_body, login

    headers = login(client)
    body = {
        **event_body(),
        "tables": [{"name": name, "capacity": 8} for name in ("A", "B")],
    }
    event = client.post("/api/events", headers=headers, json=body).json()
    path = f"/api/events/{event['id']}"
    assert (
        client.post(
            path + "/test-users", headers=headers, json={"players": 1}
        ).status_code
        == 200
    )
    with Session(client.app.state.engine) as db:
        saved = db.get(Event, event["id"])
        pid = saved.test_signups["players"][0]["id"]
        saved.test_signups = {
            **saved.test_signups,
            "players": [{**saved.test_signups["players"][0], "choices": ["A"]}],
        }
        saved.status = "open"
        saved.signup_mode = mode
        db.commit()
    assert (
        client.put(
            path + f"/manager-players/{pid}",
            headers=headers,
            json={"table": "B", "name": "Test Player 001"},
        ).status_code
        == 200
    )
    rows = client.get(path + "/signups").json()
    assert any(player["id"] == pid for player in rows[1]["players"])
    target = path + f"/players/{pid}/settings"
    assert (
        client.put(target, headers=headers, json={"guaranteed_table": "B"}).status_code
        == 200
    )
    assert (
        client.delete(
            path + f"/manager-players/{pid}", headers=headers, params={"table": "B"}
        ).status_code
        == 200
    )
    assert (
        client.put(target, headers=headers, json={"guaranteed_table": "B"}).status_code
        == 422
    )
    assert (
        client.put(target, headers=headers, json={"guaranteed_table": "A"}).status_code
        == 200
    )
