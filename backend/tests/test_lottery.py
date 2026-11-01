import itertools

import pytest

from app.lottery import assign


def snapshot(choices, capacities=(1, 1), weights=None):
    return {
        "tables": [
            {"name": name, "capacity": cap}
            for name, cap in zip(["A", "B"], capacities, strict=True)
        ],
        "players": [
            {
                "id": str(i),
                "name": f"Player {i}",
                "choices": selected,
                "weight": (weights or {}).get(str(i), 1.0),
            }
            for i, selected in enumerate(choices)
        ],
    }


def oracle_size(data):
    best = 0
    capacities = {t["name"]: t["capacity"] for t in data["tables"]}
    for assignment in itertools.product(
        *[[None, *p["choices"]] for p in data["players"]]
    ):
        if all(assignment.count(name) <= cap for name, cap in capacities.items()):
            best = max(best, sum(name is not None for name in assignment))
    return best


def test_matching_matches_brute_force_for_small_graphs():
    for choices in itertools.product([["A"], ["B"], ["A", "B"]], repeat=4):
        data = snapshot(choices)
        for seed in ("one", "two", "three"):
            result = assign(data, seed)
            assert len(result["assignments"]) == oracle_size(data)
            for row in result["tables"]:
                assert len(row["players"]) <= 1
            for pid, table in result["assignments"].items():
                assert table in data["players"][int(pid)]["choices"]
            seated = [p["id"] for table in result["tables"] for p in table["players"]]
            assert len(seated) == len(set(seated)) == len(result["assignments"])
            assert set(seated) == set(result["assignments"])
            assert result["waitlist"] == [
                pid for pid in result["order"] if pid not in result["assignments"]
            ]
            for table in result["tables"]:
                assert [p["id"] for p in table["waitlist"]] == [
                    pid
                    for pid in result["waitlist"]
                    if table["name"] in data["players"][int(pid)]["choices"]
                ]


def test_flexible_player_moves_without_losing_their_place():
    data = snapshot([["A", "B"], ["A"]])
    for n in range(100):
        result = assign(data, str(n))
        assert result["assignments"] == {"0": "B", "1": "A"}


def test_replay_is_independent_of_player_and_choice_input_order():
    data = snapshot([["A", "B"], ["A"], ["B"], ["A", "B"]])
    result = assign(data, "fixed")
    data["players"].reverse()
    for player in data["players"]:
        player["choices"].reverse()
    assert assign(data, "fixed") == result


def test_later_players_never_evict_an_earlier_accepted_player():
    data = snapshot([["A"], ["A"], ["A"], ["A"]])
    result = assign(data, "priority")
    assert list(result["assignments"]) == result["order"][:1]


def test_weight_two_wins_approximately_two_thirds_of_pairwise_draws():
    data = snapshot([["A"], ["A"]], weights={"0": 2.0})
    wins = sum("0" in assign(data, str(seed))["assignments"] for seed in range(1000))
    assert 610 < wins < 730


@pytest.mark.parametrize("weight", [0, -1, 0.01, 11, float("nan"), float("inf")])
def test_invalid_weights_rejected(weight):
    with pytest.raises(ValueError):
        assign(snapshot([["A"]], weights={"0": weight}), "seed")


def test_empty_lottery_and_ample_capacity():
    assert assign(snapshot([]), "empty")["waitlist"] == []
    result = assign(snapshot([["A"], ["A"], ["B"]], capacities=(8, 8)), "room")
    assert len(result["assignments"]) == 3
    assert result["waitlist"] == []


def test_guaranteed_players_always_seated_ahead_of_weighted_players():
    data = snapshot([["A"], ["A"], ["A", "B"]], weights={"0": 0.1, "1": 10})
    data["players"][0]["guaranteed_seat"] = True
    for seed in range(100):
        result = assign(data, str(seed))
        assert result["assignments"]["0"] == "A"
        assert result["assignments"]["2"] == "B"
        assert result["waitlist"] == ["1"]


def test_reserved_table_stays_fixed_while_flexible_guarantees_can_move():
    data = snapshot([["A", "B"], ["A", "B"], ["A"]])
    data["players"][0].update(guaranteed_seat=True, guaranteed_table="B")
    data["players"][1]["guaranteed_seat"] = True
    for seed in range(50):
        assert assign(data, str(seed))["assignments"] == {"0": "B", "1": "A"}


def test_conflicting_guarantees_and_unselected_reservations_rejected():
    from app.lottery import GuaranteeConflict

    data = snapshot([["A"], ["A"]])
    for p in data["players"]:
        p["guaranteed_seat"] = True
    with pytest.raises(GuaranteeConflict, match="exceed capacity"):
        assign(data, "seed")
    data["players"][0]["guaranteed_table"] = "B"
    with pytest.raises(GuaranteeConflict, match="reserved table"):
        assign(data, "seed")
