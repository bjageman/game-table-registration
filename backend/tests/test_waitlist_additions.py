"""Late waitlist entries preserve the draw and share normal promotion behavior."""

import time
from copy import deepcopy

import pytest
from flow_helpers import closing_event, closing_message
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.announcements import payloads
from app.models import (
    Announcement,
    AssignmentPreference,
    Event,
    LotteryRun,
    PlayerProfile,
    PromotionDM,
)
from app.waitlists import add_player
from app.withdrawals import current_result, manager_add, manager_remove, withdraw


def profile(engine, player_id="4"):
    with Session(engine) as db:
        db.add(
            PlayerProfile(
                guild_id="guild",
                discord_id=player_id,
                discord_name="Late Player",
                is_test=player_id.startswith("test-"),
            )
        )
        db.commit()


@pytest.mark.parametrize("method", ["manager", "discord", "manual"])
@pytest.mark.parametrize("player_id", ["4", "test-" + "a" * 24])
def test_append_order_draw_preservation_and_promotion(promotion_db, method, player_id):
    engine = promotion_db
    profile(engine, player_id)
    with Session(engine) as db:
        run = db.get(LotteryRun, "event")
        original = (deepcopy(run.snapshot), deepcopy(run.result))
        db.get(AssignmentPreference, "user:owner").announce_table_changes = True
        db.commit()
    assert add_player(engine, "guild", "event", player_id, "Table A")
    assert not add_player(engine, "guild", "event", player_id, "Table A")
    with Session(engine) as db:
        run = db.get(LotteryRun, "event")
        current = current_result(db, run)
        assert [p["id"] for p in current["tables"][0]["waitlist"]] == [
            "2",
            "3",
            player_id,
        ]
        assert current["assignments"] == {"1": "Table A"}
        assert current["waitlist"] == ["2", "3", player_id]
        assert (run.snapshot, run.result) == original
        assert not list(db.scalars(select(PromotionDM)))
        posts = payloads(db.get(Event, "event"), "channel", current, run.snapshot)
        assert (
            "Late Player" in str(posts)
            if player_id.startswith("test-")
            else f"<@{player_id}>" in str(posts)
        )
        assert db.scalar(select(Announcement).where(Announcement.kind == "refresh"))
    assert manager_remove(engine, "guild", "event", "1")
    assert manager_remove(engine, "guild", "event", "2")
    if method == "manager":
        assert manager_remove(engine, "guild", "event", "3")
    elif method == "discord":
        assert withdraw(engine, "guild", "channel", "assignment-message", "3")
    else:
        assert manager_add(engine, "guild", "event", player_id, "Table A")
    with Session(engine) as db:
        current = current_result(db, db.get(LotteryRun, "event"))
        assert current["assignments"][player_id] == "Table A"
        assert current["tables"][0]["waitlist"] == []
        notices = list(
            db.scalars(select(PromotionDM).where(PromotionDM.discord_id == player_id))
        )
        assert len(notices) == (0 if player_id.startswith("test-") else 1)


def test_same_player_can_wait_for_multiple_tables(promotion_db):
    engine = promotion_db
    profile(engine)
    with Session(engine) as db:
        event = db.get(Event, "event")
        event.tables = [*event.tables, {"name": "Table B", "capacity": 1}]
        run = db.get(LotteryRun, "event")
        run.result = {
            **run.result,
            "tables": [
                *run.result["tables"],
                {"name": "Table B", "players": [], "waitlist": []},
            ],
        }
        db.commit()
    assert add_player(engine, "guild", "event", "4", "Table A")
    assert add_player(engine, "guild", "event", "4", "Table B")
    with Session(engine) as db:
        current = current_result(db, db.get(LotteryRun, "event"))
        assert current["waitlist"].count("4") == 1
    assert manager_add(engine, "guild", "event", "4", "Table B")
    with Session(engine) as db:
        current = current_result(db, db.get(LotteryRun, "event"))
        assert all(
            not any(p["id"] == "4" for p in table["waitlist"])
            for table in current["tables"]
        )


def test_waitlist_api_permissions_validation_and_state(client):
    headers, event, path, _ = closing_event(client)
    engine = client.app.state.engine
    profile(engine)
    # Player 4 signed up for B; adding to A must be rejected while still open.
    target = path + "/waitlisted-players/4"
    body = {"table": "A"}
    assert client.post(target, headers=headers, json=body).status_code == 409
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    # Use an unseated profile independent of the random draw.
    profile(engine, "999")
    target = path + "/waitlisted-players/999"
    assert client.post(target, json=body).status_code == 403
    assert (
        client.post(target, headers=headers, json={"table": "missing"}).status_code
        == 409
    )
    assert (
        client.post(
            path + "/waitlisted-players/888", headers=headers, json=body
        ).status_code
        == 409
    )
    assert client.post(target, headers=headers, json=body).status_code == 200
    assert client.post(target, headers=headers, json=body).status_code == 409
    rows = client.get(path + "/signups").json()
    assert (
        next(row for row in rows if row["name"] == "A")["waitlist"][-1]["id"] == "999"
    )
    seated = next(p["id"] for row in rows for p in row["players"])
    assert (
        client.post(
            path + f"/waitlisted-players/{seated}", headers=headers, json=body
        ).status_code
        == 409
    )
    with Session(engine) as db:
        db.get(Event, event["id"]).archived_at = time.time()
        db.commit()
    assert (
        client.post(
            path + "/waitlisted-players/4", headers=headers, json=body
        ).status_code
        == 409
    )
    with Session(engine) as db:
        db.get(Event, event["id"]).created_by = "another-owner"
        db.commit()
    assert client.post(target, headers=headers, json=body).status_code == 404
