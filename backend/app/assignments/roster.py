"""Project the saved draw and subsequent edits into the current roster."""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    EventManagerSignup,
    EventManualAssignment,
    EventTableRemoval,
    EventWaitlistAddition,
    EventWithdrawal,
    LotteryRun,
)


@dataclass
class RosterRecords:
    withdrawals: list[EventWithdrawal] = field(default_factory=list)
    manual: list[EventManualAssignment] = field(default_factory=list)
    additions: list[EventWaitlistAddition] = field(default_factory=list)
    signups: list[EventManagerSignup] = field(default_factory=list)
    exclusions: list[EventTableRemoval] = field(default_factory=list)


def _load_changes[
    RosterChange: (
        EventWithdrawal,
        EventManualAssignment,
        EventWaitlistAddition,
        EventManagerSignup,
        EventTableRemoval,
    )
](
    db: Session, model: type[RosterChange], event_ids: list[str], *ordering: Any
) -> dict[str, list[RosterChange]]:
    grouped: dict[str, list[RosterChange]] = {}
    for row in db.scalars(
        select(model).where(model.event_id.in_(event_ids)).order_by(*ordering)
    ):
        grouped.setdefault(row.event_id, []).append(row)
    return grouped


def load_roster_records(db: Session, event_ids: list[str]) -> dict[str, RosterRecords]:
    """Load roster changes in five queries regardless of the number of events."""
    if not event_ids:
        return {}
    withdrawals = _load_changes(
        db,
        EventWithdrawal,
        event_ids,
        EventWithdrawal.withdrawn_at,
        EventWithdrawal.discord_id,
    )
    manual = _load_changes(
        db,
        EventManualAssignment,
        event_ids,
        EventManualAssignment.assigned_at,
        EventManualAssignment.discord_id,
    )
    additions = _load_changes(
        db,
        EventWaitlistAddition,
        event_ids,
        EventWaitlistAddition.added_at,
        EventWaitlistAddition.discord_id,
        EventWaitlistAddition.table_name,
    )
    signups = _load_changes(db, EventManagerSignup, event_ids)
    exclusions = _load_changes(db, EventTableRemoval, event_ids)
    return {
        event_id: RosterRecords(
            withdrawals=withdrawals.get(event_id, []),
            manual=manual.get(event_id, []),
            additions=additions.get(event_id, []),
            signups=signups.get(event_id, []),
            exclusions=exclusions.get(event_id, []),
        )
        for event_id in event_ids
    }


def build_roster_players(
    db: Session, run: LotteryRun, *, records: RosterRecords | None = None
) -> dict[str, Any]:
    """Collect player identities from the draw and organizer-added memberships."""
    players = {player["id"]: player for player in run.snapshot["players"]}
    for signup in (
        records.signups
        if records is not None
        else db.scalars(
            select(EventManagerSignup).where(
                EventManagerSignup.event_id == run.event_id
            )
        )
    ):
        players.setdefault(
            signup.discord_id,
            {"id": signup.discord_id, "name": signup.discord_name},
        )
    for addition in (
        records.additions
        if records is not None
        else db.scalars(
            select(EventWaitlistAddition).where(
                EventWaitlistAddition.event_id == run.event_id
            )
        )
    ):
        players.setdefault(
            addition.discord_id,
            {"id": addition.discord_id, "name": addition.discord_name},
        )
    return players


def build_current_roster(
    db: Session, run: LotteryRun, *, records: RosterRecords | None = None
) -> dict[str, Any]:
    """Build current seats and waitlists without modifying the saved draw."""
    result = run.result
    if records is None:
        records = load_roster_records(db, [run.event_id])[run.event_id]
    rows = records.withdrawals
    withdrawn = {row.discord_id: row.withdrawn_at for row in rows}
    assignments = {
        player_id: table
        for player_id, table in result["assignments"].items()
        if player_id not in withdrawn
    }
    manual = records.manual
    placements = [
        (row.withdrawn_at, row.promoted_id, row.table_name)
        for row in rows
        if row.promoted_id
    ] + [(row.assigned_at, row.discord_id, row.table_name) for row in manual]
    for placed_at, player_id, table_name in sorted(placements):
        if placed_at > withdrawn.get(player_id, float("-inf")):
            assignments[player_id] = table_name

    additions = records.additions
    added_tables = {(row.discord_id, row.table_name) for row in additions}
    by_id = build_roster_players(db, run, records=records)
    excluded = {(row.discord_id, row.table_name) for row in records.exclusions}
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
    for table in tables:
        order = {
            pid: index
            for index, pid in enumerate(run.waitlist_order.get(table["name"], []))
        }
        table["waitlist"].sort(key=lambda player: order.get(player["id"], len(order)))
    waitlisted = {player["id"] for table in tables for player in table["waitlist"]}
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
                if pid in waitlisted
            )
        ),
        "tables": tables,
    }
