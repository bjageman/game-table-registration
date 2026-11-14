"""Place reciprocal pairs atomically, preferring shared tables before split seating."""

import hashlib
import math
from collections import Counter
from typing import Any


def active_pairs(snapshot: dict[str, Any]) -> dict[str, str]:
    players = {p["id"]: p for p in snapshot["players"]}
    links = snapshot.get("pairs", {})
    return {
        pid: partner
        for pid, partner in links.items()
        if pid != partner
        and pid in players
        and partner in players
        and links.get(partner) == pid
        and set(players[pid]["choices"]) & set(players[partner]["choices"])
    }


def assign_pairs(snapshot: dict[str, Any], seed: str) -> dict[str, Any]:
    from app.lottery import GuaranteeConflict

    people = {p["id"]: p for p in snapshot["players"]}
    capacities = {t["name"]: t["capacity"] for t in snapshot["tables"]}
    pairs = active_pairs(snapshot)
    groups = sorted(
        {tuple(sorted((pid, pairs[pid]))) if pid in pairs else (pid,) for pid in people}
    )

    def digest(label: str) -> str:
        return hashlib.sha256(f"{seed}\0{label}".encode()).hexdigest()

    def guaranteed(group: tuple[str, ...]) -> bool:
        return any(
            people[pid].get("guaranteed_seat") or people[pid].get("guaranteed_table")
            for pid in group
        )

    def priority(group: tuple[str, ...]) -> tuple[bool, bool, float, tuple[str, ...]]:
        label = group[0] if len(group) == 1 else "pair:" + ":".join(group)
        uniform = (int(digest(f"priority:{label}")[:13], 16) + 1) / (2**52 + 1)
        average = sum(float(people[pid]["weight"]) for pid in group) / len(group)
        # Preserve individual guarantees before attempting inherited pair guarantees;
        # conflicting pairs can then wait with an organizer alert instead of
        # preventing an otherwise valid draw for everyone else.
        return (
            not guaranteed(group),
            guaranteed(group) and len(group) == 2,
            -math.log(uniform) / average,
            group,
        )

    groups.sort(key=priority)
    options: dict[tuple[str, ...], list[tuple[str, ...]]] = {}
    for group in groups:
        choices = [
            set([people[pid]["guaranteed_table"]])
            if people[pid].get("guaranteed_table")
            else set(people[pid]["choices"])
            for pid in group
        ]
        shared = set.intersection(*choices)
        together = [
            (name,) * len(group)
            for name in sorted(
                shared, key=lambda name: digest(f"table:{':'.join(group)}:{name}")
            )
            if capacities[name] >= len(group)
        ]
        split = (
            sorted(
                [(a, b) for a in choices[0] for b in choices[1] if a != b],
                key=lambda option: digest(f"split:{group}:{option}"),
            )
            if len(group) == 2 and not guaranteed(group)
            else []
        )
        options[group] = together + split

    Allocation = dict[tuple[str, ...], tuple[str, ...]]

    def place(
        group: tuple[str, ...],
        allocated: Allocation,
        visited: set[tuple[str, ...]],
        locked: set[tuple[str, ...]],
        allow_split_existing: bool,
    ) -> Allocation | None:
        if group in visited:
            return None
        visited.add(group)
        previous = allocated.get(group)
        for option in options[group]:
            if previous == option:
                continue
            if (
                not allow_split_existing
                and previous is not None
                and len(group) == 2
                and previous[0] == previous[1]
                and option[0] != option[1]
            ):
                continue
            trial = {**allocated, group: option}
            while True:
                counts = Counter(name for names in trial.values() for name in names)
                full = next(
                    (
                        name
                        for name in sorted(capacities)
                        if counts[name] > capacities[name]
                    ),
                    None,
                )
                if full is None:
                    return trial
                moved = None
                # Each group is explored once per insertion, bounding the search
                # for large rosters while retaining every previously accepted group.
                for occupant in reversed(groups):
                    if (
                        occupant in locked
                        or occupant == group
                        or full not in trial.get(occupant, ())
                    ):
                        continue
                    moved = place(
                        occupant, trial, visited, locked | {group}, allow_split_existing
                    )
                    if moved is not None:
                        trial = moved
                        break
                if moved is None:
                    break
        return None

    allocated: Allocation = {}
    conflicts = []
    for group in groups:
        # Exhaust alternatives that preserve already-seated pairs first. A full
        # preferred table must not split a pair when another choice has room.
        placed = place(group, allocated, set(), set(), False)
        if placed is None:
            placed = place(group, allocated, set(), set(), True)
        if placed is not None:
            allocated = placed
        elif guaranteed(group):
            if len(group) == 1:
                raise GuaranteeConflict(
                    "Guaranteed seats exceed capacity for the selected tables. "
                    "Adjust guaranteed seats or table capacity before closing signups."
                )
            conflicts.append(
                {
                    "players": list(group),
                    "message": f"{people[group[0]]['name']} and "
                    f"{people[group[1]]['name']} were waitlisted: "
                    "their guaranteed seats cannot be honored together. "
                    "An organizer must resolve this conflict.",
                }
            )
    order = [pid for group in groups for pid in group]
    assignments = {
        pid: table
        for group, tables in allocated.items()
        for pid, table in zip(group, tables, strict=True)
    }
    waiting = [pid for pid in order if pid not in assignments]

    def display(pid: str) -> dict[str, str]:
        return {"id": pid, "name": people[pid]["name"]}

    return {
        "order": order,
        "assignments": assignments,
        "waitlist": waiting,
        "pairs": pairs,
        "pairing_conflicts": conflicts,
        "pair_guarantees": [
            pid
            for group in groups
            if len(group) == 2 and guaranteed(group)
            for pid in group
        ],
        "pairing_warnings": [conflict["message"] for conflict in conflicts],
        "tables": [
            {
                "name": table["name"],
                "players": [
                    display(pid)
                    for pid in order
                    if assignments.get(pid) == table["name"]
                ],
                "waitlist": [
                    display(pid)
                    for pid in waiting
                    if table["name"] in people[pid]["choices"]
                ],
            }
            for table in snapshot["tables"]
        ],
    }
