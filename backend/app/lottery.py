"""Replayable weighted priority and capacity-aware placement."""

import hashlib
import math
from typing import Any

VERSION = "guaranteed-weighted-matching-v2"


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

    def digest(label: str) -> str:
        return hashlib.sha256(f"{seed}\0{label}".encode()).hexdigest()

    def priority(player_id: str) -> tuple[float, str]:
        # 52-bit uniform is strictly between 0 and 1 and independent of input order.
        uniform = (int(digest(f"priority:{player_id}")[:13], 16) + 1) / (2**52 + 1)
        return -math.log(uniform) / float(by_id[player_id]["weight"]), player_id

    order = sorted(
        by_id,
        key=lambda pid: (not by_id[pid].get("guaranteed_seat", False), *priority(pid)),
    )
    rank = {pid: i for i, pid in enumerate(order)}
    choices = {
        pid: sorted(set(p["choices"]), key=lambda name: digest(f"table:{pid}:{name}"))
        for pid, p in by_id.items()
    }
    seated: dict[str, list[str]] = {name: [] for name in capacities}
    assignments: dict[str, str] = {}

    def place(pid: str, seen: set[str]) -> bool:
        for name in choices[pid]:
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
        if not place(pid, set()) and by_id[pid].get("guaranteed_seat"):
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
