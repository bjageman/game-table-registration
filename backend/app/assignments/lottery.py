"""Replayable weighted priority and capacity-aware placement."""

import math
from typing import Any

from app.assignments.randomness import digest, weighted_priority

VERSION = "paired-weighted-matching-v5"


class GuaranteeConflict(ValueError):
    pass


def assign(snapshot: dict[str, Any], seed: str) -> dict[str, Any]:
    tables = snapshot["tables"]
    players = snapshot["players"]
    capacities = {t["name"]: t["capacity"] for t in tables}
    if len(capacities) != len(tables) or any(
        not isinstance(n, int) or isinstance(n, bool) or n < 1
        for n in capacities.values()
    ):
        raise ValueError("Tables require unique names and positive capacities")
    by_id = {p["id"]: p for p in players}
    if len(by_id) != len(players):
        raise ValueError("Player IDs must be unique")
    for p in players:
        weight = float(p["weight"])
        if not math.isfinite(weight) or not 0.1 <= weight <= 10:
            raise ValueError("Player weights must be between 0.1 and 10")
        if not p["choices"] or not set(p["choices"]) <= capacities.keys():
            raise ValueError("Each player must select existing tables")
        if p.get("guaranteed_table") and p["guaranteed_table"] not in p["choices"]:
            raise ValueError("Guaranteed table must be one of the player's choices")

    from app.assignments.paired_lottery import active_pairs, assign_pairs

    if active_pairs(snapshot):
        return assign_pairs(snapshot, seed)

    def priority(player_id: str) -> tuple[float, str]:
        return weighted_priority(
            seed, player_id, float(by_id[player_id]["weight"])
        ), player_id

    order = sorted(
        by_id,
        key=lambda pid: (
            not (
                by_id[pid].get("guaranteed_seat", False)
                or by_id[pid].get("guaranteed_table")
            ),
            *priority(pid),
        ),
    )
    rank = {pid: i for i, pid in enumerate(order)}
    choices = {
        pid: sorted(
            set(p["choices"]), key=lambda name: digest(seed, f"table:{pid}:{name}")
        )
        for pid, p in by_id.items()
    }
    seated: dict[str, list[str]] = {name: [] for name in capacities}
    assignments: dict[str, str] = {}

    def place(pid: str, seen: set[str]) -> bool:
        for name in (
            [by_id[pid]["guaranteed_table"]]
            if by_id[pid].get("guaranteed_table")
            else choices[pid]
        ):
            if name in seen:
                continue
            seen.add(name)
            if len(seated[name]) < capacities[name]:
                seated[name].append(pid)
                assignments[pid] = name
                return True
            for occupant in list(seated[name]):
                if place(occupant, seen):
                    seated[name].remove(occupant)
                    seated[name].append(pid)
                    assignments[pid] = name
                    return True
        return False

    for pid in order:
        if not place(pid, set()) and (
            by_id[pid].get("guaranteed_seat") or by_id[pid].get("guaranteed_table")
        ):
            raise GuaranteeConflict(
                "Guaranteed seats exceed capacity for the selected tables. "
                "Adjust guaranteed seats or table capacity before closing signups."
            )
    waiting = [pid for pid in order if pid not in assignments]

    def display(pid: str) -> dict[str, str]:
        return {"id": pid, "name": by_id[pid]["name"]}

    return {
        "order": order,
        "assignments": assignments,
        "waitlist": waiting,
        "tables": [
            {
                "name": t["name"],
                "players": [
                    display(pid)
                    for pid in sorted(seated[t["name"]], key=rank.__getitem__)
                ],
                "waitlist": [
                    display(pid) for pid in waiting if t["name"] in choices[pid]
                ],
            }
            for t in tables
        ],
    }
