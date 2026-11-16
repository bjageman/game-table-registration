"""Swaps preserve placements, waitlist rank, draw history, and later edits."""

from copy import deepcopy

import pytest
from flow_helpers import closing_event, closing_message
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.assignments.player_changes import (
    add_player_to_waitlist,
    remove_player_from_roster,
    withdraw_from_announcement,
)
from app.assignments.roster import build_current_roster
from app.assignments.swaps import swap_players
from app.models import Announcement, Event, LotteryRun, PromotionDM
from app.schemas import SwapPlayersInput


def setup_tables(engine, status="assigned"):
    with Session(engine) as db:
        event = db.get(Event, "event")
        event.status = status
        if status == "review":
            db.execute(delete(Announcement))
        event.tables = [*event.tables, {"name": "Table B", "capacity": 1}]
        run = db.get(LotteryRun, "event")
        people = [{"id": "4", "name": "Dan"}, {"id": "5", "name": "Eve"}]
        run.snapshot = {**run.snapshot, "players": [*run.snapshot["players"], *people]}
        run.result = {
            **run.result,
            "assignments": {"1": "Table A", "4": "Table B"},
            "waitlist": ["2", "3", "5"],
            "tables": [
                *run.result["tables"],
                {
                    "name": "Table B",
                    "players": [people[0]],
                    "waitlist": [people[1]],
                },
            ],
        }
        original = deepcopy((run.snapshot, run.result))
        db.commit()
        return original


def roster(engine):
    with Session(engine) as db:
        return build_current_roster(db, db.get(LotteryRun, "event"))


def swap(engine, first="1", second="4", waiting=False, other_waiting=False):
    return swap_players(
        engine,
        "guild",
        "event",
        SwapPlayersInput(
            player_id=first,
            table="Table A",
            waitlist=waiting,
            other_player_id=second,
            other_table="Table B",
            other_waitlist=other_waiting,
        ),
    )


@pytest.mark.parametrize("status", ["review", "assigned"])
@pytest.mark.parametrize(
    "first,second,waiting,other_waiting,assigned,lists",
    [
        ("1", "4", False, False, {"1": "Table B", "4": "Table A"}, [["2", "3"], ["5"]]),
        ("1", "5", False, True, {"4": "Table B", "5": "Table A"}, [["2", "3"], ["1"]]),
        ("3", "4", True, False, {"1": "Table A", "3": "Table B"}, [["2", "4"], ["5"]]),
        ("3", "5", True, True, {"1": "Table A", "4": "Table B"}, [["2", "5"], ["3"]]),
    ],
)
def test_swap_preserves_other_players_and_draw(
    promotion_db,
    status,
    first,
    second,
    waiting,
    other_waiting,
    assigned,
    lists,
):
    original = setup_tables(promotion_db, status)
    assert swap(promotion_db, first, second, waiting, other_waiting)
    current = roster(promotion_db)
    assert current["assignments"] == assigned
    assert [[p["id"] for p in t["waitlist"]] for t in current["tables"]] == lists
    with Session(promotion_db) as db:
        run = db.get(LotteryRun, "event")
        assert (run.snapshot, run.result) == original
        assert not list(db.scalars(select(PromotionDM)))
        if status == "review":
            assert not list(db.scalars(select(Announcement)))


def test_swapped_waitlist_rank_survives_removal_rejoin_and_repeat_swap(promotion_db):
    setup_tables(promotion_db)
    assert swap(promotion_db, "3", "4", True)
    assert remove_player_from_roster(promotion_db, "guild", "event", "1")
    assert roster(promotion_db)["assignments"] == {"2": "Table A", "3": "Table B"}
    assert remove_player_from_roster(promotion_db, "guild", "event", "2")
    assert roster(promotion_db)["assignments"] == {"4": "Table A", "3": "Table B"}
    assert swap(promotion_db, "4", "3")
    assert roster(promotion_db)["assignments"] == {"4": "Table B", "3": "Table A"}
    assert add_player_to_waitlist(promotion_db, "guild", "event", "1", "Table B")
    assert [p["id"] for p in roster(promotion_db)["tables"][1]["waitlist"]] == [
        "5",
        "1",
    ]


@pytest.mark.parametrize("method", ["manager", "discord"])
def test_disabled_promotions_leave_seat_empty_and_manual_swap_still_works(
    promotion_db, method
):
    setup_tables(promotion_db)
    with Session(promotion_db) as db:
        db.get(Event, "event").auto_promote_waitlist = False
        db.commit()
    if method == "manager":
        assert remove_player_from_roster(promotion_db, "guild", "event", "1")
    else:
        assert withdraw_from_announcement(
            promotion_db, "guild", "channel", "assignment-message", "1"
        )
    assert roster(promotion_db)["assignments"] == {"4": "Table B"}
    assert swap(promotion_db, "2", "4", True)
    assert roster(promotion_db)["assignments"] == {"2": "Table B"}
    assert [p["id"] for p in roster(promotion_db)["tables"][0]["waitlist"]] == [
        "4",
        "3",
    ]


@pytest.mark.parametrize(
    "invalid",
    ["stale", "same_table", "same_player", "archived", "wrong_guild", "publishing"],
)
def test_invalid_swap_is_atomic(promotion_db, invalid):
    setup_tables(promotion_db)
    body = SwapPlayersInput(
        player_id="1", table="Table A", other_player_id="4", other_table="Table B"
    )
    guild = "guild"
    with Session(promotion_db) as db:
        if invalid == "stale":
            body.other_waitlist = True
        elif invalid == "same_table":
            body.other_table = "Table A"
        elif invalid == "same_player":
            body.other_player_id = "1"
        elif invalid == "archived":
            db.get(Event, "event").archived_at = 1
        elif invalid == "wrong_guild":
            guild = "other"
        else:
            db.get(Event, "event").status = "review"
        db.commit()
    before = roster(promotion_db)
    assert not swap_players(promotion_db, guild, "event", body)
    assert roster(promotion_db) == before


def test_swap_and_toggle_api_scope_and_csrf(client):
    headers, _, path, _ = closing_event(client, review=True)
    body = dict(player_id="2", table="A", other_player_id="4", other_table="B")
    assert (
        client.post(path + "/swap-players", headers=headers, json=body).status_code
        == 409
    )
    assert (
        client.put(
            path + "/waitlist-settings",
            headers=headers,
            json={"auto_promote_waitlist": False},
        ).status_code
        == 409
    )
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    rows = client.get(path + "/signups").json()
    first, second = (row["players"][0]["id"] for row in rows)
    body.update(player_id=first, other_player_id=second)
    assert client.post(path + "/swap-players", json=body).status_code == 403
    assert (
        client.post(path + "/swap-players", headers=headers, json=body).status_code
        == 200
    )
    setting = {"auto_promote_waitlist": False}
    assert client.put(path + "/waitlist-settings", json=setting).status_code == 403
    assert (
        client.put(path + "/waitlist-settings", headers=headers, json=setting).json()
        == setting
    )
    assert (
        next(e for e in client.get("/api/events").json() if path.endswith(e["id"]))[
            "auto_promote_waitlist"
        ]
        is False
    )
    with Session(client.app.state.engine) as db:
        db.get(Event, path.split("/")[-1]).created_by = "someone-else"
        db.commit()
    assert (
        client.post(path + "/swap-players", headers=headers, json=body).status_code
        == 404
    )
    assert (
        client.put(
            path + "/waitlist-settings", headers=headers, json=setting
        ).status_code
        == 404
    )
