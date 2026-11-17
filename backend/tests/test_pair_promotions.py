"""Pairings do not change individual waitlist promotion or manual edits."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assignments.player_changes import (
    assign_player_to_table,
    remove_player_from_roster,
)
from app.assignments.roster import build_current_roster
from app.models import LotteryRun, PromotionDM


def save_pairings(engine):
    with Session(engine) as db:
        run = db.get(LotteryRun, "event")
        run.snapshot = {**run.snapshot, "pairings": {"2": ["3"], "3": ["2"]}}
        db.commit()


def test_promotes_one_waiter_without_needing_their_paired_player(promotion_db):
    save_pairings(promotion_db)
    assert remove_player_from_roster(promotion_db, "guild", "event", "1")
    with Session(promotion_db) as db:
        current = build_current_roster(db, db.get(LotteryRun, "event"))
        assert current["assignments"] == {"2": "Table A"}
        assert current["waitlist"] == ["3"]
        assert list(db.scalars(select(PromotionDM.discord_id))) == ["2"]


def test_manual_addition_does_not_automatically_move_the_paired_player(promotion_db):
    save_pairings(promotion_db)
    assert assign_player_to_table(promotion_db, "guild", "event", "2", "Table A")
    with Session(promotion_db) as db:
        current = build_current_roster(db, db.get(LotteryRun, "event"))
        assert current["assignments"]["2"] == "Table A"
        assert "3" in current["waitlist"]
        assert "3" not in current["assignments"]
