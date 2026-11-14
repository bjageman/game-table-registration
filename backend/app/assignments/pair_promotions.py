"""Choose an automatic replacement without splitting a waiting pair."""

from typing import Any

from app.models import Event


def replacements(
    event: Event, current: dict[str, Any], table_name: str
) -> list[tuple[str, str]]:
    tables = {row["name"]: row for row in current["tables"]}
    free = {
        row["name"]: row["capacity"]
        - len(tables[row["name"]]["players"])
        + int(row["name"] == table_name)
        for row in event.tables
    }
    waiting = set(current["waitlist"])
    pairs = current.get("pairs", {})
    blocked = {
        pid
        for conflict in current.get("pairing_conflicts", [])
        for pid in conflict["players"]
    }
    for candidate in tables[table_name]["waitlist"]:
        pid = candidate["id"]
        partner = pairs.get(pid)
        if pid in blocked or (partner and partner in blocked):
            continue
        if not partner or partner not in waiting:
            if free[table_name] >= 1:
                return [(pid, table_name)]
            continue
        eligible = [
            name
            for name, row in tables.items()
            if any(player["id"] == partner for player in row["waitlist"])
        ]
        if table_name in eligible and free[table_name] >= 2:
            return [(pid, table_name), (partner, table_name)]
        if pid not in current.get("pair_guarantees", []):
            for other in sorted(eligible):
                if other != table_name and free[table_name] >= 1 and free[other] >= 1:
                    return [(pid, table_name), (partner, other)]
    return []
