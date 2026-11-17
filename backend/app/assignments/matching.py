"""Capacity-aware placement shared by individual selection and preference layout."""


def place_player(
    player_id: str,
    choices: dict[str, list[str]],
    capacities: dict[str, int],
    seated: dict[str, list[str]],
    assignments: dict[str, str],
    seen: set[str],
    *,
    fixed: frozenset[str] = frozenset(),
) -> bool:
    """Find a seat, moving accepted occupants without evicting or moving fixed IDs."""
    for name in choices[player_id]:
        if name in seen:
            continue
        seen.add(name)
        if len(seated[name]) < capacities[name]:
            seated[name].append(player_id)
            assignments[player_id] = name
            return True
        for occupant in list(seated[name]):
            if occupant not in fixed and place_player(
                occupant, choices, capacities, seated, assignments, seen, fixed=fixed
            ):
                seated[name].remove(occupant)
                seated[name].append(player_id)
                assignments[player_id] = name
                return True
    return False
