"""Best-effort direct pairings, after individual lottery winners are fixed."""

from typing import Any

from app.assignments.matching import place_player
from app.assignments.randomness import digest

# Bound optional optimization independently of the number of saved pairings.
MAX_ATTEMPTS = 1000


def arrange_pairings(
    snapshot: dict[str, Any],
    seed: str,
    assignments: dict[str, str],
    order: list[str],
) -> dict[str, str]:
    """Improve direct matches without evicting winners or moving guaranteed tables.

    Try each unmatched edge at shared tables, reserving those two seats and
    matching every other winner around them. Accept only a strict increase in
    satisfied direct edges, prioritizing the shortest lists. This is deterministic
    and deliberately best effort:
    overlapping pairings do not become mandatory transitive groups.
    """
    pairings = snapshot.get("pairings", {})
    rank = {pid: index for index, pid in enumerate(order)}
    winners = [pid for pid in order if pid in assignments]
    players = {p["id"]: p for p in snapshot["players"]}
    capacities = {t["name"]: t["capacity"] for t in snapshot["tables"]}
    choices = {
        pid: [players[pid]["guaranteed_table"]]
        if players[pid].get("guaranteed_table")
        else sorted(
            set(players[pid]["choices"]),
            key=lambda name: digest(seed, f"table:{pid}:{name}"),
        )
        for pid in winners
    }
    edges = sorted(
        {
            (min(pid, other), max(pid, other))
            for pid, others in pairings.items()
            if pid in assignments
            for other in others
            if other in assignments and other != pid and pid in pairings.get(other, [])
        },
        key=lambda edge: (
            min(rank[edge[0]], rank[edge[1]]),
            max(rank[edge[0]], rank[edge[1]]),
        ),
    )

    # Use saved list lengths so one pairing outranks a longer list even
    # when some of that longer list's players did not win seats.
    degrees = {pid: len(set(pairings.get(pid, [])) - {pid}) for pid in winners}
    edge_priority = {edge: min(degrees[edge[0]], degrees[edge[1]]) for edge in edges}
    edges.sort(key=lambda edge: edge_priority[edge])
    bucket_indices = {
        priority: index
        for index, priority in enumerate(sorted(set(edge_priority.values())))
    }

    def score(placement: dict[str, str]) -> tuple[int, ...]:
        # Lexicographic buckets keep a single-choice match ahead of any number
        # of matches from larger lists, while still allowing partial matches.
        counts = [0] * len(bucket_indices)
        for a, b in edges:
            if placement[a] == placement[b]:
                counts[bucket_indices[edge_priority[(a, b)]]] += 1
        return tuple(counts)

    best = dict(assignments)
    best_score = score(best)
    attempts = 0
    improved = True
    while improved and attempts < MAX_ATTEMPTS:
        improved = False
        for first, second in edges:
            if best[first] == best[second]:
                continue
            shared = sorted(
                set(choices[first]) & set(choices[second]),
                key=lambda name: digest(seed, f"preference:{first}:{second}:{name}"),
            )
            for table in shared:
                if attempts >= MAX_ATTEMPTS:
                    return best
                attempts += 1
                if capacities[table] < 2:
                    continue
                candidate = _match_winners(
                    winners, choices, capacities, best, (first, second), table
                )
                if candidate is None:
                    continue
                candidate_score = score(candidate)
                if candidate_score > best_score:
                    best, best_score = candidate, candidate_score
                    improved = True
                    break
    return best


def _match_winners(
    winners: list[str],
    choices: dict[str, list[str]],
    capacities: dict[str, int],
    previous: dict[str, str],
    pair: tuple[str, str],
    table: str,
) -> dict[str, str] | None:
    """Reserve a paired players, then retain every other already-selected winner."""
    seated: dict[str, list[str]] = {name: [] for name in capacities}
    seated[table] = list(pair)
    result = dict.fromkeys(pair, table)

    ordered_choices = {
        pid: [previous[pid], *(name for name in choices[pid] if name != previous[pid])]
        for pid in winners
    }
    for pid in winners:
        if pid not in pair and not place_player(
            pid,
            ordered_choices,
            capacities,
            seated,
            result,
            set(),
            fixed=frozenset(pair),
        ):
            return None
    return result
