"""Seat swaps exchange visible slots and keep the saved draw unchanged."""

from copy import deepcopy

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.assignments.player_changes import (
    assign_player_to_table,
    remove_player_from_roster,
)
from app.assignments.roster import build_current_roster
from app.assignments.swaps import swap_players
from app.models import Announcement, Event, LotteryRun
from app.schemas import SwapPlayersInput


def setup_draw(engine, status="assigned"):
    people = [{"id": str(i), "name": f"Player {i}"} for i in range(1, 13)]
    tables = [
        {"name": "A", "players": people[:5], "waitlist": [people[10]]},
        {"name": "B", "players": people[5:10], "waitlist": [people[11]]},
    ]
    with Session(engine) as db:
        event = db.get(Event, "event")
        event.status = status
        event.tables = [{"name": name, "capacity": 5} for name in ("A", "B")]
        if status == "review":
            db.execute(delete(Announcement))
        run = db.get(LotteryRun, "event")
        run.snapshot = {"players": people, "tables": event.tables}
        run.result = {
            "tables": tables,
            "waitlist": ["11", "12"],
            "assignments": {p["id"]: t["name"] for t in tables for p in t["players"]},
        }
        original = deepcopy((run.snapshot, run.result))
        db.commit()
        return original


def current(engine):
    with Session(engine) as db:
        return build_current_roster(db, db.get(LotteryRun, "event"))


def seats(engine):
    return [[p["id"] for p in t["players"]] for t in current(engine)["tables"]]


def swap(
    engine,
    first="4",
    second="6",
    first_table="A",
    second_table="B",
    waiting=False,
    other_waiting=False,
):
    assert swap_players(
        engine,
        "guild",
        "event",
        SwapPlayersInput(
            player_id=first,
            table=first_table,
            waitlist=waiting,
            other_player_id=second,
            other_table=second_table,
            other_waitlist=other_waiting,
        ),
    )


@pytest.mark.parametrize("status", ["review", "assigned"])
def test_top_and_fourth_exchange_slots_and_repeated_swaps_preserve_draw(
    promotion_db, status
):
    original = setup_draw(promotion_db, status)
    swap(promotion_db)
    assert seats(promotion_db) == [
        ["1", "2", "3", "6", "5"],
        ["4", "7", "8", "9", "10"],
    ]
    swap(promotion_db, "6", "4")
    assert seats(promotion_db) == [
        ["1", "2", "3", "4", "5"],
        ["6", "7", "8", "9", "10"],
    ]
    with Session(promotion_db) as db:
        run = db.get(LotteryRun, "event")
        assert (run.snapshot, run.result) == original


@pytest.mark.parametrize("same_table", [True, False])
def test_waitlisted_player_takes_the_exact_seat_and_swap_can_be_reversed(
    promotion_db, same_table
):
    setup_draw(promotion_db)
    target, table = ("11", "A") if same_table else ("12", "B")
    swap(promotion_db, second=target, second_table=table, other_waiting=True)
    assert seats(promotion_db) == [
        ["1", "2", "3", target, "5"],
        ["6", "7", "8", "9", "10"],
    ]
    waiting = next(t for t in current(promotion_db)["tables"] if t["name"] == table)[
        "waitlist"
    ]
    assert [p["id"] for p in waiting] == ["4"]
    swap(promotion_db, first=target, second="4", second_table=table, other_waiting=True)
    assert seats(promotion_db)[0] == ["1", "2", "3", "4", "5"]


def test_later_removal_promotion_and_readdition_do_not_restore_stale_slots(
    promotion_db,
):
    setup_draw(promotion_db)
    swap(promotion_db)
    assert remove_player_from_roster(promotion_db, "guild", "event", "6")
    assert seats(promotion_db)[0] == ["1", "2", "3", "5", "11"]
    assert assign_player_to_table(
        promotion_db, "guild", "event", "6", "A", allow_known_player=True
    )
    assert seats(promotion_db)[0] == ["1", "2", "3", "5", "11", "6"]
    assert remove_player_from_roster(promotion_db, "guild", "event", "1")
    assert seats(promotion_db)[0] == ["2", "3", "5", "11", "6"]
    assert seats(promotion_db)[1] == ["4", "7", "8", "9", "10"]
