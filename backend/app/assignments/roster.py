"""Project the saved draw and subsequent edits into the current roster."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.events.table_membership import removals
from app.models import (
    EventManagerSignup,
    EventManualAssignment,
    EventWaitlistAddition,
    EventWithdrawal,
    LotteryRun,
)


def build_roster_players(db: Session, run: LotteryRun) -> dict[str, Any]:
    """Collect player identities from the draw and organizer-added memberships."""
    players = {player["id"]: player for player in run.snapshot["players"]}
    for signup in db.scalars(
        select(EventManagerSignup).where(EventManagerSignup.event_id == run.event_id)
    ):
        players.setdefault(
            signup.discord_id,
            {"id": signup.discord_id, "name": signup.discord_name},
        )
    for addition in db.scalars(
        select(EventWaitlistAddition).where(
            EventWaitlistAddition.event_id == run.event_id
        )
    ):
        players.setdefault(
            addition.discord_id,
            {"id": addition.discord_id, "name": addition.discord_name},
        )
    return players


def build_current_roster(db: Session, run: LotteryRun) -> dict[str, Any]:
    """Build current seats and waitlists without modifying the saved draw."""
    result = run.result
    rows = list(
        db.scalars(
            select(EventWithdrawal)
            .where(EventWithdrawal.event_id == run.event_id)
            .order_by(EventWithdrawal.withdrawn_at, EventWithdrawal.discord_id)
        )
    )
    withdrawn = {row.discord_id: row.withdrawn_at for row in rows}
    assignments = {
        player_id: table
        for player_id, table in result["assignments"].items()
        if player_id not in withdrawn
    }
    manual = list(
        db.scalars(
            select(EventManualAssignment)
            .where(EventManualAssignment.event_id == run.event_id)
            .order_by(
                EventManualAssignment.assigned_at, EventManualAssignment.discord_id
            )
        )
    )
    placements = [
        (row.withdrawn_at, row.promoted_id, row.table_name)
        for row in rows
        if row.promoted_id
    ] + [(row.assigned_at, row.discord_id, row.table_name) for row in manual]
    for placed_at, player_id, table_name in sorted(placements):
        if placed_at > withdrawn.get(player_id, float("-inf")):
            assignments[player_id] = table_name

    additions = list(
        db.scalars(
            select(EventWaitlistAddition)
            .where(EventWaitlistAddition.event_id == run.event_id)
            .order_by(
                EventWaitlistAddition.added_at,
                EventWaitlistAddition.discord_id,
                EventWaitlistAddition.table_name,
            )
        )
    )
    added_tables = {(row.discord_id, row.table_name) for row in additions}
    by_id = build_roster_players(db, run)
    excluded = removals(db, run.event_id)
    tables = []
    for table in result["tables"]:
        name = table["name"]
        players = [
            dict(player)
            for player in table["players"]
            if assignments.get(player["id"]) == name
        ]
        included = {player["id"] for player in players}
        for player_id, table_name in assignments.items():
            if table_name == name and player_id not in included:
                player = by_id[player_id]
                players.append({"id": player_id, "name": player["name"]})
        # A rejoining player belongs at the end, never at their original rank.
        waitlist = [
            player
            for player in table.get("waitlist", [])
            if player["id"] not in withdrawn
            and (player["id"], name) not in added_tables
        ]
        waitlist.extend(
            {"id": addition.discord_id, "name": addition.discord_name}
            for addition in additions
            if addition.table_name == name
            and addition.added_at > withdrawn.get(addition.discord_id, float("-inf"))
        )
        tables.append(
            {
                **table,
                "players": players,
                "waitlist": [
                    dict(player)
                    for player in waitlist
                    if player["id"] not in assignments
                    and (player["id"], name) not in excluded
                ],
            }
        )
    return {
        **result,
        "pairing_warnings": [
            conflict["message"]
            for conflict in result.get("pairing_conflicts", [])
            if not all(pid in assignments for pid in conflict["players"])
        ],
        "assignments": assignments,
        "waitlist": list(
            dict.fromkeys(
                pid
                for pid in [*result["waitlist"], *[row.discord_id for row in additions]]
                if any(
                    player["id"] == pid
                    for table in tables
                    for player in table["waitlist"]
                )
            )
        ),
        "tables": tables,
    }
