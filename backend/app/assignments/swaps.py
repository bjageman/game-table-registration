"""Exchange two selected placements in one locked transaction."""

import time

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.assignments.notifications import enqueue_table_change, format_roster_players
from app.assignments.placement_records import (
    record_manual_assignment,
    record_waitlist_addition,
    record_withdrawal,
)
from app.assignments.player_changes import lock_assignment_for_edit
from app.assignments.roster import build_current_roster, build_roster_players
from app.discord.discord_format import clean
from app.discord.event_messages import enqueue_roster_refresh
from app.events.table_membership import set_removed
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
        same_table = body.table == body.other_table
        if body.player_id == body.other_player_id or (
            same_table and not (body.waitlist or body.other_waitlist)
        ):
            return False
        # A player waiting for several tables is identified by the selected row.
        tables = {row["name"]: row for row in current["tables"]}
        for pid, table, waiting in placements:
            if table not in tables or not any(
                p["id"] == pid
                for p in tables[table]["waitlist" if waiting else "players"]
            ):
                return False
        changed_at = time.time()
        replacements: dict[str, dict[str, str]] = {}
        for index, (pid, table, waiting) in enumerate(placements):
            if waiting:
                replacements.setdefault(table, {})[pid] = placements[1 - index][0]
        run.waitlist_order = {
            name: list(
                dict.fromkeys(
                    replacements.get(name, {}).get(p["id"], p["id"])
                    for p in row["waitlist"]
                )
            )
            for name, row in tables.items()
        }
        for index, (pid, table, waiting) in enumerate(placements):
            if same_table and body.waitlist and body.other_waitlist:
                break
            _, destination, destination_waiting = placements[1 - index]
            if not waiting:
                record_withdrawal(db, event_id, pid, table, changed_at, None)
            else:
                set_removed(db, event_id, pid, table, True)
            if destination_waiting:
                record_waitlist_addition(
                    db,
                    event_id,
                    pid,
                    destination,
                    known[pid]["name"],
                    changed_at + 0.000001,
                )
            else:
                record_manual_assignment(
                    db,
                    event_id,
                    pid,
                    destination,
                    changed_at + 0.000001,
                )
            set_removed(db, event_id, pid, destination, False)
        if event.status == "assigned":
            swapped_names = format_roster_players(
                known, [body.player_id, body.other_player_id]
            )
            enqueue_table_change(
                db,
                event,
                f"Placements swapped: {swapped_names} "
                f"between **{clean(body.table)}** and **{clean(body.other_table)}**.",
                [body.player_id, body.other_player_id],
                nonce_key=f"{event_id}:swap:{changed_at}",
                created_at=changed_at,
            )
            enqueue_roster_refresh(db, event)
        db.commit()
        return True
