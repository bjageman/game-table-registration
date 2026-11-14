from types import SimpleNamespace
from unittest.mock import MagicMock

from app.events.signups import apply_manager_players, apply_manager_signups


def test_removal_keeps_other_table_choices_in_roster_and_draw():
    db = MagicMock()
    db.scalars.return_value = [
        SimpleNamespace(
            discord_id="1", discord_name="Player", removed=True, choices=["B"]
        )
    ]
    event = SimpleNamespace(id="event")
    rows = apply_manager_signups(
        db,
        event,
        [
            {"name": name, "players": [{"id": "1", "name": "Player"}]}
            for name in ("A", "B")
        ],
    )
    assert rows[0]["players"] == []
    assert rows[1]["players"] == [{"id": "1", "name": "Player"}]
    players = apply_manager_players(
        db, event, [{"id": "1", "name": "Player", "choices": ["A", "B"]}]
    )
    assert players[0]["choices"] == ["B"]
