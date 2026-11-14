from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assignments.waitlists import add_player
from app.assignments.withdrawals import current_result, manager_add, manager_remove
from app.models import (
    Announcement,
    AssignmentPreference,
    Event,
    LotteryRun,
    PlayerProfile,
    PromotionDM,
)


def pair_waitlist(engine, *, capacity=1, split=False):
    with Session(engine) as db:
        event = db.get(Event, "event")
        event.tables = [{"name": "Table A", "capacity": capacity}]
        run = db.get(LotteryRun, "event")
        result = deepcopy(run.result)
        result["pairs"] = {"2": "3", "3": "2"}
        if split:
            event.tables = [*event.tables, {"name": "Table B", "capacity": 1}]
            result["tables"].append(
                {
                    "name": "Table B",
                    "players": [],
                    "waitlist": [{"id": "3", "name": "Carol"}],
                }
            )
        run.result = result
        db.commit()


def test_pair_waits_for_two_seats_and_single_behind_them_gets_one(promotion_db):
    engine = promotion_db
    pair_waitlist(engine)
    with Session(engine) as db:
        db.add(
            PlayerProfile(
                scope_key="user:owner",
                guild_id="guild",
                discord_id="4",
                discord_name="Single",
            )
        )
        db.commit()
    assert add_player(engine, "guild", "event", "4", "Table A")
    assert manager_remove(engine, "guild", "event", "1")
    with Session(engine) as db:
        current = current_result(db, db.get(LotteryRun, "event"))
        assert current["assignments"] == {"4": "Table A"}
        assert current["waitlist"] == ["2", "3"]


def test_pair_promotes_together_when_two_seats_are_available(promotion_db):
    engine = promotion_db
    pair_waitlist(engine, capacity=2)
    assert manager_remove(engine, "guild", "event", "1")
    with Session(engine) as db:
        current = current_result(db, db.get(LotteryRun, "event"))
        assert current["assignments"] == {"2": "Table A", "3": "Table A"}
        assert current["waitlist"] == []
        assert set(db.scalars(select(PromotionDM.discord_id))) == {"2", "3"}


def test_pair_can_promote_to_separate_eligible_tables_if_both_get_a_seat(promotion_db):
    engine = promotion_db
    pair_waitlist(engine, split=True)
    with Session(engine) as db:
        db.get(AssignmentPreference, "user:owner").announce_table_changes = True
        db.commit()
    assert manager_remove(engine, "guild", "event", "1")
    with Session(engine) as db:
        current = current_result(db, db.get(LotteryRun, "event"))
        assert current["assignments"] == {"2": "Table A", "3": "Table B"}
        assert current["waitlist"] == []
        notices = list(db.scalars(select(PromotionDM)))
        assert {(notice.discord_id, notice.table_name) for notice in notices} == {
            ("2", "Table A"),
            ("3", "Table B"),
        }
        post = db.scalar(select(Announcement).where(Announcement.kind == "promotion"))
        assert (
            "<@2> has been promoted from the waitlist to **Table A**."
            in post.payload["content"]
        )
        assert (
            "<@3> has been promoted from the waitlist to **Table B**."
            in post.payload["content"]
        )


def test_manual_addition_does_not_automatically_move_the_partner(promotion_db):
    engine = promotion_db
    pair_waitlist(engine)
    assert manager_add(engine, "guild", "event", "2", "Table A")
    with Session(engine) as db:
        current = current_result(db, db.get(LotteryRun, "event"))
        assert current["assignments"]["2"] == "Table A"
        assert "3" in current["waitlist"]
        assert "3" not in current["assignments"]


def test_one_partner_withdrawing_does_not_remove_the_other(promotion_db):
    engine = promotion_db
    pair_waitlist(engine, capacity=2)
    assert manager_add(engine, "guild", "event", "2", "Table A")
    assert manager_remove(engine, "guild", "event", "1")
    with Session(engine) as db:
        current = current_result(db, db.get(LotteryRun, "event"))
        assert current["assignments"]["2"] == "Table A"
