"""Exchange two selected placements in one locked transaction."""

import time

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.assignments.notifications import enqueue_table_change
from app.assignments.player_changes import _record_withdrawal, lock_assignment_for_edit
from app.assignments.roster import build_current_roster, build_roster_players
from app.discord.discord_format import clean
from app.discord.event_messages import enqueue_roster_refresh
from app.events.table_membership import set_removed
from app.models import EventManualAssignment, EventWaitlistAddition
from app.schemas import SwapPlayersInput


def swap_players(
    engine: Engine, guild_id: str, event_id: str, body: SwapPlayersInput
) -> bool:
    with Session(engine) as db:
        locked = lock_assignment_for_edit(db, guild_id, event_id)
        if locked is None:
            return False
        event, run = locked
        current = build_current_roster(db, run)
        known = build_roster_players(db, run)
        placements = [
            (body.player_id, body.table, body.waitlist),
            (body.other_player_id, body.other_table, body.other_waitlist),
        ]
        if body.player_id == body.other_player_id or body.table == body.other_table:
            return False
        # A player waiting for several tables is identified by the selected row.
        tables = {row["name"]: row for row in current["tables"]}
        for pid, table, waiting in placements:
            if table not in tables or not any(
                p["id"] == pid
                for p in tables[table]["waitlist" if waiting else "players"]
            ):
                return False
        # Do not offer someone who already belongs to the source table.
        for pid, table, _ in placements:
            other = body.other_table if table == body.table else body.table
            if any(
                p["id"] == pid
                for key in ("players", "waitlist")
                for p in tables[other][key]
            ):
                return False
        changed_at = time.time()
        order = {
            row["name"]: [p["id"] for p in row["waitlist"]] for row in current["tables"]
        }
        for index, (pid, table, waiting) in enumerate(placements):
            other_id, destination, destination_waiting = placements[1 - index]
            if not waiting:
                _record_withdrawal(db, event_id, pid, table, changed_at, None)
            else:
                set_removed(db, event_id, pid, table, True)
            if destination_waiting:
                addition = db.get(EventWaitlistAddition, (event_id, pid, destination))
                if addition is None:
                    addition = EventWaitlistAddition(
                        event_id=event_id, discord_id=pid, table_name=destination
                    )
                    db.add(addition)
                addition.discord_name = known[pid]["name"]
                addition.added_at = changed_at + 0.000001
                order[destination] = [
                    pid if entry == other_id else entry for entry in order[destination]
                ]
            else:
                assignment = db.get(EventManualAssignment, (event_id, pid))
                if assignment is None:
                    assignment = EventManualAssignment(
                        event_id=event_id, discord_id=pid
                    )
                    db.add(assignment)
                assignment.table_name = destination
                assignment.assigned_at = changed_at + 0.000001
            set_removed(db, event_id, pid, destination, False)
        run.waitlist_order = order
        if event.status == "assigned":
            enqueue_table_change(
                db,
                event,
                "Placements swapped: "
                + " and ".join(
                    clean(known[pid]["name"])
                    if pid.startswith("test-")
                    else f"<@{pid}>"
                    for pid in (body.player_id, body.other_player_id)
                )
                + " "
                f"between **{clean(body.table)}** and **{clean(body.other_table)}**.",
                [body.player_id, body.other_player_id],
                nonce_key=f"{event_id}:swap:{changed_at}",
                created_at=changed_at,
            )
            enqueue_roster_refresh(db, event)
        db.commit()
        return True
