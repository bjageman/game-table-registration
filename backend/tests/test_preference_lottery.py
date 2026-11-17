"""Preferences rearrange individual winners and never inherit guarantees."""

from copy import deepcopy

import pytest

from app.assignments.lottery import assign


def snapshot(capacity=2):
    return {
        "tables": [
            {"name": "A", "capacity": capacity},
            {"name": "B", "capacity": capacity},
        ],
        "players": [
            {"id": str(i), "name": str(i), "weight": i, "choices": ["A", "B"]}
            for i in range(1, 9)
        ],
    }


@pytest.mark.parametrize("seed", [str(i) for i in range(100)])
def test_preferences_preserve_winners_priority_waitlist_capacity_and_replay(seed):
    data = snapshot()
    data["players"][0]["guaranteed_seat"] = True
    data["players"][1]["guaranteed_table"] = "B"
    baseline = assign(data, seed)
    winners = list(baseline["assignments"])
    # Alice's waitlisted preferences cannot gain a seat or inherit her guarantee.
    data["paired_preferences"] = {
        "1": [str(i) for i in range(2, 9)],
        **{str(i): ["1"] for i in range(2, 9)},
    }
    saved = deepcopy(data)
    result = assign(data, seed)
    assert data == saved
    assert result == assign(deepcopy(data), seed)
    assert result["order"] == baseline["order"]
    assert result["waitlist"] == baseline["waitlist"]
    assert set(result["assignments"]) == set(winners)
    assert result["assignments"]["2"] == "B"
    assert "1" in result["assignments"]
    for table in result["tables"]:
        assert len(table["players"]) <= 2
        for player in table["players"]:
            assert result["assignments"][player["id"]] == table["name"]
    assert "pair_guarantees" not in result


def test_alice_and_david_match_while_bob_and_carl_remain_waitlisted():
    data = snapshot(1)
    data["tables"] = [{"name": "A", "capacity": 2}]
    data["players"] = [
        {
            "id": pid,
            "name": pid,
            "weight": 5,
            "choices": ["A"],
            "guaranteed_seat": pid in ("Alice", "David"),
        }
        for pid in ("Alice", "Bob", "Carl", "David")
    ]
    data["paired_preferences"] = {
        "Alice": ["Bob", "Carl", "David"],
        **{pid: ["Alice"] for pid in ("Bob", "Carl", "David")},
    }
    result = assign(data, "example")
    assert result["assignments"] == {"Alice": "A", "David": "A"}
    assert set(result["waitlist"]) == {"Bob", "Carl"}


def test_guarantee_does_not_pull_companion_in_or_waitlist_guaranteed_player():
    data = {
        "tables": [{"name": "A", "capacity": 1}],
        "players": [
            {
                "id": pid,
                "name": pid,
                "weight": 5,
                "choices": ["A"],
                "guaranteed_seat": pid == "Alice",
            }
            for pid in ("Alice", "Bob")
        ],
        "paired_preferences": {"Alice": ["Bob"], "Bob": ["Alice"]},
    }
    result = assign(data, "one seat")
    assert result["assignments"] == {"Alice": "A"}
    assert result["waitlist"] == ["Bob"]


def test_rearranges_winners_at_full_tables_to_match_direct_preferences():
    data = snapshot()
    data["players"] = data["players"][:4]
    baseline = assign(data, "swap")
    a = baseline["tables"][0]["players"][0]["id"]
    b = baseline["tables"][1]["players"][0]["id"]
    data["paired_preferences"] = {a: [b], b: [a]}
    result = assign(data, "swap")
    assert result["assignments"][a] == result["assignments"][b]
    assert set(result["assignments"]) == set(baseline["assignments"])


def test_overlapping_preferences_can_share_three_seats_without_becoming_atomic():
    data = snapshot(3)
    data["players"] = data["players"][:6]
    data["paired_preferences"] = {"1": ["2", "3"], "2": ["1"], "3": ["1"]}
    result = assign(data, "star")
    assert len({result["assignments"][pid] for pid in ("1", "2", "3")}) == 1


def test_incompatible_table_choices_leave_winners_seated_separately():
    data = snapshot(1)
    data["players"] = data["players"][:2]
    data["players"][0]["choices"] = ["A"]
    data["players"][1]["choices"] = ["B"]
    data["paired_preferences"] = {"1": ["2"], "2": ["1"]}
    assert assign(data, "choices")["assignments"] == {"1": "A", "2": "B"}


@pytest.mark.parametrize("seed", range(30))
def test_varied_graphs_preserve_constraints_and_ignore_list_order(seed):
    import random

    rng = random.Random(seed)
    tables = ["A", "B", "C", "D"]
    data = {
        "tables": [{"name": name, "capacity": rng.randint(1, 4)} for name in tables],
        "players": [
            {
                "id": str(i),
                "name": str(i),
                "weight": rng.uniform(0.1, 10),
                "choices": rng.sample(tables, rng.randint(1, 4)),
            }
            for i in range(20)
        ],
    }
    baseline = assign(data, str(seed))
    preferences = {str(i): [] for i in range(20)}
    for i in range(20):
        for j in range(i + 1, 20):
            if rng.random() < 0.2:
                preferences[str(i)].append(str(j))
                preferences[str(j)].append(str(i))
    data["paired_preferences"] = preferences
    result = assign(data, str(seed))
    assert result["order"] == baseline["order"]
    assert result["waitlist"] == baseline["waitlist"]
    assert set(result["assignments"]) == set(baseline["assignments"])
    for player in data["players"]:
        if player["id"] in result["assignments"]:
            assert result["assignments"][player["id"]] in player["choices"]
    for table in data["tables"]:
        assert (
            sum(name == table["name"] for name in result["assignments"].values())
            <= table["capacity"]
        )

    data["paired_preferences"] = {
        pid: list(reversed(others))
        for pid, others in reversed(list(preferences.items()))
    }
    assert assign(data, str(seed)) == result


def single_preference_snapshot():
    return {
        "tables": [{"name": "A", "capacity": 3}, {"name": "B", "capacity": 2}],
        "players": [
            {"id": pid, "name": pid, "weight": 5, "choices": choices}
            for pid, choices in (
                ("Alice", ["A", "B"]),
                ("Anya", ["B"]),
                ("Bob", ["A"]),
                ("Carl", ["A"]),
            )
        ],
        "paired_preferences": {
            "Alice": ["Anya", "Bob", "Carl"],
            "Anya": ["Alice"],
            "Bob": ["Alice", "Carl"],
            "Carl": ["Alice", "Bob"],
        },
    }


@pytest.mark.parametrize("seed", [str(i) for i in range(10)])
def test_single_preference_takes_priority_over_more_matches_in_larger_lists(seed):
    data = single_preference_snapshot()
    baseline = assign({**data, "paired_preferences": {}}, seed)
    result = assign(data, seed)
    assert set(result["assignments"]) == set(baseline["assignments"])
    assert result["assignments"]["Alice"] == result["assignments"]["Anya"] == "B"
    assert result["assignments"]["Bob"] == result["assignments"]["Carl"] == "A"


def test_saved_list_length_counts_even_if_some_preferences_did_not_win_seats():
    data = {
        "tables": [{"name": "A", "capacity": 2}, {"name": "B", "capacity": 1}],
        "players": [
            {
                "id": pid,
                "name": pid,
                "weight": 5,
                "choices": ["A", "B"],
                "guaranteed_seat": pid == "Bob",
            }
            for pid in ("Alice", "Anya", "Bob")
        ],
        "paired_preferences": {
            "Alice": ["Anya", "Bob"],
            "Anya": ["Alice"],
            "Bob": ["Alice", "Absent"],
            "Absent": ["Bob"],
        },
    }
    # Bob wins earlier but still has a longer list than Anya, even though only
    # Alice from his list is seated. This cannot override Anya's sole preference.
    result = assign(data, "absent preferences")
    assert result["assignments"]["Alice"] == result["assignments"]["Anya"] == "A"
    assert result["assignments"]["Bob"] == "B"
