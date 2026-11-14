"""Organizer additions to the end of an assigned table's waitlist."""

import time

from sqlalchemy import Engine, update
from sqlalchemy.orm import Session

from app.assignments.withdrawals import current_result, result_players
from app.discord.announcements import enqueue_refresh
from app.discord.event_threads import queue_member
from app.models import (
    Event,
    EventWaitlistAddition,
    LotteryRun,
)
from app.players.player_profiles import for_event as player_scope_for_event


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
                Event.status.in_(["assigned", "review"]),
                Event.archived_at.is_(None),
            )
            .values(status=Event.status)
            .returning(Event.id)
        ).scalar_one_or_none()
        if claimed is None:
            return False
        run = db.get(LotteryRun, event_id)
        event = db.get(Event, event_id)
        assert event is not None
        profile = player_scope_for_event(event).get(db, player_id)
        if run is None:
            return False
        known = result_players(db, run).get(player_id)
        if profile is None and known is None:
            return False
        current = current_result(db, run)
        table = next(
            (row for row in current["tables"] if row["name"] == table_name), None
        )
        if (
            table is None
            or player_id in current["assignments"]
            or any(player["id"] == player_id for player in table["waitlist"])
            or (
                player_id.startswith("test-")
                and profile is not None
                and not profile.is_test
            )
        ):
            return False
        if profile is not None:
            name = profile.discord_name
        else:
            assert known is not None
            name = known["name"]
        addition = db.get(EventWaitlistAddition, (event_id, player_id, table_name))
        if addition is None:
            db.add(
                EventWaitlistAddition(
                    event_id=event_id,
                    discord_id=player_id,
                    table_name=table_name,
                    discord_name=name,
                    added_at=time.time(),
                )
            )
        else:
            addition.discord_name = name
            addition.added_at = time.time()
        event = db.get(Event, event_id)
        assert event is not None
        queue_member(db, event, player_id)
        if event.status == "assigned":
            enqueue_refresh(db, event)
        db.commit()
        return True
