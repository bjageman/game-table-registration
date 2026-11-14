"""Pairing scenarios agreed with the organizer for issue 156."""

import hashlib
import math
from copy import deepcopy

import pytest

from app.lottery import assign


def draw(choices, capacities, **fields):
    players = [
        {
            "id": str(i),
            "name": f"Player {i}",
            "choices": names,
            "weight": 5.0,
            **fields.get(str(i), {}),
        }
        for i, names in enumerate(choices, 1)
    ]
    return {
        "players": players,
        "tables": [{"name": name, "capacity": n} for name, n in capacities.items()],
        "pairs": {"1": "2", "2": "1"},
    }


def test_absent_partner_participates_alone_and_no_common_choices_are_independent():
    alone = draw([["A"]], {"A": 1})
    assert assign(alone, "solo")["assignments"] == {"1": "A"}
    separate = draw([["A"], ["B"]], {"A": 1, "B": 1})
    assert assign(separate, "separate")["assignments"] == {"1": "A", "2": "B"}


def test_shared_table_is_preferred_to_splitting():
    data = draw([["A", "C"], ["B", "C"]], {"A": 1, "B": 1, "C": 2})
    for seed in map(str, range(30)):
        assert assign(data, seed)["assignments"] == {"1": "C", "2": "C"}


def test_split_is_allowed_only_when_both_can_be_seated():
    data = draw([["A", "C"], ["B", "C"]], {"A": 1, "B": 1, "C": 1})
    for seed in map(str, range(30)):
        result = assign(data, seed)
        assert set(result["assignments"]) == {"1", "2"}
        assert len(set(result["assignments"].values())) == 2
    partial = draw(
        [["A", "C"], ["B", "C"], ["B"], ["C"]],
        {"A": 1, "B": 1, "C": 1},
        **{"3": {"guaranteed_seat": True}, "4": {"guaranteed_seat": True}},
    )
    result = assign(partial, "partial")
    assert set(result["assignments"]) == {"3", "4"}
    assert result["waitlist"] == ["1", "2"]


def test_single_seat_goes_to_single_player_and_pair_waits():
    data = draw([["A"], ["A"], ["A"]], {"A": 1})
    for seed in map(str, range(30)):
        result = assign(data, seed)
        assert result["assignments"] == {"3": "A"}
        assert result["waitlist"] == ["1", "2"]


def test_pair_uses_one_average_weight_draw():
    data = draw(
        [["A"], ["A"], ["A"]],
        {"A": 3},
        **{"1": {"weight": 8}, "2": {"weight": 2}, "3": {"weight": 4}},
    )
    for seed in map(str, range(30)):

        def score(label, weight):
            digest = hashlib.sha256(f"{seed}\0priority:{label}".encode()).hexdigest()
            uniform = (int(digest[:13], 16) + 1) / (2**52 + 1)
            return -math.log(uniform) / weight

        expected = (
            ["1", "2", "3"] if score("pair:1:2", 5) < score("3", 4) else ["3", "1", "2"]
        )
        assert assign(data, seed)["order"] == expected


def test_guarantee_extends_to_partner_without_changing_their_profile():
    data = draw([["A"], ["A"], ["A"]], {"A": 2}, **{"1": {"guaranteed_seat": True}})
    result = assign(data, "guarantee")
    assert result["assignments"] == {"1": "A", "2": "A"}
    assert not result["pairing_warnings"]
    assert "guaranteed_seat" not in data["players"][1]


@pytest.mark.parametrize("conflicting", [False, True])
def test_guaranteed_pair_conflicts_are_waitlisted_with_an_alert(conflicting):
    data = draw(
        [["A", "C"], ["B", "C"]],
        {"A": 1, "B": 1, "C": 1},
        **{"1": {"guaranteed_seat": True}},
    )
    if conflicting:
        data["players"][0]["guaranteed_table"] = "A"
        data["players"][1]["guaranteed_table"] = "B"
    result = assign(data, "conflict")
    assert result["assignments"] == {}
    assert result["waitlist"] == ["1", "2"]
    assert len(result["pairing_warnings"]) == 1
    assert "organizer" in result["pairing_warnings"][0]


def test_pairs_replay_independently_of_input_order_and_respect_capacity():
    data = draw([["A", "B"], ["A", "B"], ["A"], ["B"]], {"A": 2, "B": 2})
    for seed in map(str, range(30)):
        expected = assign(data, seed)
        changed = deepcopy(data)
        changed["players"].reverse()
        for player in changed["players"]:
            player["choices"].reverse()
        assert assign(changed, seed) == expected
        assert set(expected["assignments"]) == {"1", "2", "3", "4"}
        assert all(len(row["players"]) <= 2 for row in expected["tables"])


def test_pair_guarantee_conflict_does_not_abort_other_guaranteed_players():
    data = draw(
        [["A"], ["A"], ["A"]],
        {"A": 2},
        **{"1": {"guaranteed_seat": True}, "3": {"guaranteed_seat": True}},
    )
    result = assign(data, "guarantees")
    assert result["assignments"] == {"3": "A"}
    assert result["waitlist"] == ["1", "2"]
    assert result["pairing_warnings"]


def test_later_player_uses_alternative_vacancy_without_splitting_a_seated_pair():
    data = draw(
        [["A", "C"], ["B", "C"], ["B", "C"]],
        {"A": 1, "B": 1, "C": 2},
        **{"1": {"weight": 10}, "2": {"weight": 10}, "3": {"weight": 0.1}},
    )
    for seed in map(str, range(40)):
        result = assign(data, seed)
        assert result["assignments"]["1"] == result["assignments"]["2"] == "C"
        assert result["assignments"]["3"] == "B"


def test_split_relocation_remains_available_when_no_pair_preserving_option_fits():
    data = draw(
        [["A", "C"], ["B", "C"], ["C"]],
        {"A": 1, "B": 1, "C": 2},
        **{"1": {"weight": 10}, "2": {"weight": 10}, "3": {"weight": 0.1}},
    )
    for seed in map(str, range(40)):
        result = assign(data, seed)
        assert set(result["assignments"]) == {"1", "2", "3"}
        assert result["assignments"]["3"] == "C"
        assert result["assignments"]["1"] != result["assignments"]["2"]
