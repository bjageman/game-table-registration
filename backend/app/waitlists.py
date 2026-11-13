"""Organizer additions to the end of an assigned table's waitlist."""

import time

from sqlalchemy import Engine, update
from sqlalchemy.orm import Session

from app.announcements import enqueue_refresh
from app.event_threads import queue_member
from app.models import (
    Event,
    EventWaitlistAddition,
    EventWithdrawal,
    LotteryRun,
    PlayerProfile,
)
from app.withdrawals import current_result


def add_player(
    engine: Engine, guild_id: str, event_id: str, player_id: str, table_name: str
) -> bool:
    with Session(engine) as db:
        # Serialize roster changes with assignments and withdrawals.
        claimed = db.execute(
            update(Event)
            .where(
                Event.id == event_id,
                Event.guild_id == guild_id,
                Event.status == "assigned",
                Event.archived_at.is_(None),
            )
            .values(status=Event.status)
            .returning(Event.id)
        ).scalar_one_or_none()
        if claimed is None:
            return False
        run = db.get(LotteryRun, event_id)
        profile = db.get(PlayerProfile, (guild_id, player_id))
        if run is None or profile is None:
            return False
        current = current_result(db, run)
        table = next(
            (row for row in current["tables"] if row["name"] == table_name), None
        )
        if (
            table is None
            or player_id in current["assignments"]
            or any(player["id"] == player_id for player in table["waitlist"])
            or db.get(EventWithdrawal, (event_id, player_id)) is not None
            or (player_id.startswith("test-") and not profile.is_test)
        ):
            return False
        db.add(
            EventWaitlistAddition(
                event_id=event_id,
                discord_id=player_id,
                table_name=table_name,
                discord_name=profile.discord_name,
                added_at=time.time(),
            )
        )
        event = db.get(Event, event_id)
        assert event is not None
        queue_member(db, event, player_id)
        enqueue_refresh(db, event)
        db.commit()
        return True
