"""Guarantees validate against the same effective roster shown to organizers."""

import pytest
from flow_helpers import closing_event
from sqlalchemy.orm import Session

from app.models import Event, PlayerProfile


@pytest.mark.parametrize("mode", ["poll", "custom", "reactions"])
@pytest.mark.parametrize("is_test", [False, True])
def test_manually_added_players_can_be_guaranteed_only_on_current_table(
    client, mode, is_test
):
    headers, event, path, _ = closing_event(client)
    player_id = "test-" + "a" * 24 if is_test else "123"
    with Session(client.app.state.engine) as db:
        db.get(Event, event["id"]).signup_mode = mode
        db.add(
            PlayerProfile(
                scope_key="user:owner",
                guild_id="guild",
                discord_id=player_id,
                discord_name="Player",
                weighting=5,
                is_test=is_test,
            )
        )
        db.commit()
    client.app.state.discord.table_signups.return_value = [
        {"name": "A", "players": []},
        {"name": "B", "players": []},
    ]
    player_path = path + f"/manager-players/{player_id}"
    assert (
        client.put(
            player_path, headers=headers, json={"table": "B", "name": "Player"}
        ).status_code
        == 200
    )
    roster = client.get(path + "/signups").json()
    assert any(p["id"] == player_id for p in roster[1]["players"])
    setting = path + f"/players/{player_id}/settings"
    result = client.put(setting, headers=headers, json={"guaranteed_table": "B"})
    assert result.status_code == 200
    assert result.json()["guaranteed_table"] == "B"
    assert (
        client.put(setting, headers=headers, json={"guaranteed_table": "A"}).status_code
        == 422
    )
    assert client.delete(player_path + "?table=B", headers=headers).status_code == 200
    assert (
        client.put(setting, headers=headers, json={"guaranteed_table": "B"}).status_code
        == 422
    )


@pytest.mark.parametrize("mode", ["poll", "custom", "reactions"])
def test_generated_players_still_support_guarantees(client, mode):
    headers, event, path, _ = closing_event(client)
    player_id = "test-" + "b" * 24
    with Session(client.app.state.engine) as db:
        saved = db.get(Event, event["id"])
        saved.signup_mode = mode
        saved.test_signups = {
            "players": [
                {"id": player_id, "name": "Test Player", "choices": ["A"], "weight": 5},
            ]
        }
        db.commit()
    setting = path + f"/players/{player_id}/settings"
    result = client.put(setting, headers=headers, json={"guaranteed_table": "A"})
    assert result.status_code == 200
    assert result.json()["guaranteed_table"] == "A"
