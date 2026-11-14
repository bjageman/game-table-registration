"""Players API integration coverage."""

import time

import pytest
from flow_helpers import closing_event, closing_message, event_body, login
from sqlalchemy.orm import Session as DBSession


def test_player_profiles_are_scoped_to_guild_and_global_weight_can_be_edited(client):
    from app.models import PlayerProfile

    headers = login(client)
    client.app.state.discord.bot.return_value = {"username": "mary"}
    with DBSession(client.app.state.engine) as db:
        db.add(
            PlayerProfile(
                scope_key="user:owner",
                guild_id="other",
                discord_id="123",
                discord_name="Other",
                real_name="Private",
                weighting=2.0,
            )
        )
        db.commit()
    assert client.get("/api/players/123").json()["real_name"] == ""
    created = client.put(
        "/api/players/123",
        headers=headers,
        json={"real_name": "Mary", "weighting": 5},
    )
    assert created.status_code == 200
    assert created.json()["weighting"] == 5
    updated = client.put(
        "/api/players/123",
        headers=headers,
        json={"real_name": "Mary", "weighting": 2.5},
    )
    assert updated.status_code == 200
    assert updated.json()["weighting"] == 2.5
    assert client.get("/api/players/123").json()["weighting"] == 2.5
    for invalid in (0, 10.1):
        assert (
            client.put(
                "/api/players/123",
                headers=headers,
                json={"real_name": "Mary", "weighting": invalid},
            ).status_code
            == 422
        )
    assert (
        client.put(
            "/api/players/123", headers=headers, json={"real_name": "x" * 101}
        ).status_code
        == 422
    )
    assert client.get("/api/players/invalid").status_code == 422
    saved = client.put("/api/players/123", headers=headers, json={"real_name": "Mary"})
    assert saved.json()["weighting"] == 2.5
    with DBSession(client.app.state.engine) as db:
        assert (
            db.get(PlayerProfile, ("user:owner", "other", "123")).real_name == "Private"
        )
        assert db.get(PlayerProfile, ("user:owner", "other", "123")).weighting == 2.0


def test_event_player_settings_are_scoped_and_frozen_for_assignment(client):
    headers, event, path, _ = closing_event(client)
    discord = client.app.state.discord
    discord.table_signups.return_value = [
        {"name": "A", "players": [{"id": "1", "name": "Mary"}]},
        {"name": "B", "players": [{"id": "1", "name": "Mary"}]},
    ]
    discord.bot.return_value = {"username": "Mary"}
    assert (
        client.put(
            "/api/players/1", headers=headers, json={"real_name": ""}
        ).status_code
        == 200
    )
    setting = path + "/players/1/settings"
    assert client.put(setting, json={"guaranteed_table": "B"}).status_code == 403
    assert (
        client.put(setting, headers=headers, json={"guaranteed_table": "C"}).status_code
        == 422
    )
    assert (
        client.put(setting, headers=headers, json={"guaranteed_table": "B"}).status_code
        == 200
    )
    assert (
        client.put(setting, headers=headers, json={"weighting": 2.5}).status_code == 200
    )
    rows = client.get(path + "/signups").json()
    assert rows[0]["players"][0]["guaranteed_table"] == "B"
    assert rows[1]["players"][0]["weighting"] == 2.5
    assert client.get("/api/players/1").json()["weighting"] == 5.0
    assert client.get("/api/players/1").json()["guaranteed_seat"] is False
    discord.poll_message.return_value = closing_message()
    closed = client.post(path + "/close", headers=headers)
    assert closed.status_code == 200
    run = client.get(path + "/assignments").json()
    mary = next(p for p in run["snapshot"]["players"] if p["id"] == "1")
    assert mary["weight"] == 2.5
    assert mary["guaranteed_table"] == "B"
    assert run["result"]["assignments"]["1"] == "B"
    assert (
        client.put(setting, headers=headers, json={"weighting": 3}).status_code == 409
    )


def test_manager_can_overfill_from_waitlist_without_auto_promotion_on_remove(client):
    from app.models import Announcement, EventWithdrawal

    headers, event, path, _ = closing_event(client)
    assert (
        client.put(
            "/api/settings/assignment",
            headers=headers,
            json={
                "automatic_weight_adjustment": True,
                "announce_table_changes": True,
                "post_discord_updates_to_thread": False,
            },
        ).status_code
        == 200
    )
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    rows = client.get(path + "/signups").json()
    table = next(row for row in rows if row["waitlist"])
    seated = table["players"][0]["id"]
    waiting = table["waitlist"][0]["id"]
    target = f"{path}/assigned-players/{waiting}"
    assert client.post(target, json={"table": table["name"]}).status_code == 403
    assert (
        client.post(target, headers=headers, json={"table": "missing"}).status_code
        == 409
    )
    assert (
        client.post(target, headers=headers, json={"table": table["name"]}).status_code
        == 200
    )
    assert (
        client.post(target, headers=headers, json={"table": table["name"]}).status_code
        == 409
    )
    updated = next(
        row
        for row in client.get(path + "/signups").json()
        if row["name"] == table["name"]
    )
    assert len(updated["players"]) == 2
    assert len({player["id"] for player in updated["players"]}) == 2
    assert waiting not in {player["id"] for player in updated["waitlist"]}
    assert (
        client.get(path + "/assignments").json()["current_result"]["assignments"][
            waiting
        ]
        == table["name"]
    )
    assert (
        client.delete(f"{path}/manager-players/{seated}", headers=headers).status_code
        == 200
    )
    after = next(
        row
        for row in client.get(path + "/signups").json()
        if row["name"] == table["name"]
    )
    assert [player["id"] for player in after["players"]] == [waiting]
    assert [player["id"] for player in after["waitlist"]] == [
        player["id"] for player in updated["waitlist"]
    ]
    with DBSession(client.app.state.engine) as db:
        notice = (
            db.query(Announcement)
            .filter_by(event_id=event["id"], kind="promotion")
            .order_by(Announcement.part.desc())
            .first()
        )
        assert notice is not None
        assert (
            notice.payload["content"]
            == f"<@{seated}> has left their seat at **{table['name']}**."
        )
        assert notice.payload["allowed_mentions"] == {"parse": [], "users": [seated]}
        withdrawal = db.get(EventWithdrawal, (event["id"], seated))
        assert withdrawal is not None and withdrawal.promoted_id is None
        assert (
            db.query(Announcement)
            .filter_by(event_id=event["id"], kind="refresh")
            .count()
            == 1
        )


def test_manager_remove_from_full_table_promotes_next_waitlisted_player(client):
    from app.models import Announcement, EventWithdrawal

    headers, event, path, _ = closing_event(client)
    assert (
        client.put(
            "/api/settings/assignment",
            headers=headers,
            json={
                "automatic_weight_adjustment": True,
                "announce_table_changes": True,
                "post_discord_updates_to_thread": False,
            },
        ).status_code
        == 200
    )
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    table = next(row for row in client.get(path + "/signups").json() if row["waitlist"])
    seated = table["players"][0]["id"]
    promoted = table["waitlist"][0]["id"]
    assert (
        client.delete(f"{path}/manager-players/{seated}", headers=headers).status_code
        == 200
    )
    after = next(
        row
        for row in client.get(path + "/signups").json()
        if row["name"] == table["name"]
    )
    assert [player["id"] for player in after["players"]] == [promoted]
    with DBSession(client.app.state.engine) as db:
        withdrawal = db.get(EventWithdrawal, (event["id"], seated))
        assert withdrawal is not None and withdrawal.promoted_id == promoted
        notice = (
            db.query(Announcement)
            .filter_by(event_id=event["id"], kind="promotion")
            .one()
        )
        expected = (
            f"<@{promoted}> has been promoted from the waitlist to **{table['name']}**."
        )
        assert notice.payload["content"] == expected


def test_display_names_are_guild_scoped_and_clear_to_discord_name(client):
    from app.models import PlayerProfile

    headers = login(client)
    client.app.state.discord.bot.return_value = {"username": "MaryDiscord"}
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    path = f"/api/events/{event['id']}"
    client.post(path + "/publish", headers=headers)
    client.app.state.discord.table_signups.return_value = [
        {"name": "Clocktower", "players": [{"id": "123", "name": "MaryDiscord"}]}
    ]
    with DBSession(client.app.state.engine) as db:
        db.add(
            PlayerProfile(
                scope_key="user:owner",
                guild_id="other",
                discord_id="123",
                discord_name="OtherDiscord",
                real_name="Private Display",
            )
        )
        db.commit()
    assert "display_name" not in client.get(path + "/signups").json()[0]["players"][0]
    client.put(
        "/api/players/123", headers=headers, json={"real_name": " Mary Display "}
    )
    player = client.get(path + "/signups").json()[0]["players"][0]
    assert player == {
        "id": "123",
        "name": "MaryDiscord",
        "display_name": "Mary Display",
        "weighting": 5.0,
        "guaranteed_table": None,
        "guaranteed_seat": False,
    }
    client.put("/api/players/123", headers=headers, json={"real_name": "   "})
    assert client.get(path + "/signups").json()[0]["players"][0] == {
        "id": "123",
        "name": "MaryDiscord",
        "weighting": 5.0,
        "guaranteed_table": None,
        "guaranteed_seat": False,
    }


@pytest.mark.parametrize("enabled", [True, False])
def test_automatic_weight_adjustment_once_per_draw_and_setting_scope(client, enabled):
    from app.models import AssignmentPreference, PlayerProfile

    headers, event, path, _ = closing_event(client)
    assert client.get("/api/settings/assignment").json() == {
        "show_open_signup_players": True,
        "review_assignments_before_discord": False,
        "dm_waitlist_promotions": True,
        "timezone": None,
        "automatic_weight_adjustment": True,
        "announce_table_changes": True,
        "post_discord_updates_to_thread": True,
    }
    assert (
        client.put(
            "/api/settings/assignment",
            json={
                "automatic_weight_adjustment": enabled,
                "announce_table_changes": False,
                "post_discord_updates_to_thread": False,
            },
        ).status_code
        == 403
    )
    assert (
        client.put(
            "/api/settings/assignment",
            headers=headers,
            json={
                "automatic_weight_adjustment": enabled,
                "announce_table_changes": False,
                "post_discord_updates_to_thread": False,
            },
        ).status_code
        == 200
    )
    assert (
        client.get("/api/settings/assignment").json()["automatic_weight_adjustment"]
        is enabled
    )
    with DBSession(client.app.state.engine) as db:
        db.add(
            AssignmentPreference(
                scope_key="user:other",
                automatic_weight_adjustment=not enabled,
                announce_table_changes=True,
            )
        )
        db.add(
            PlayerProfile(
                scope_key="user:owner",
                guild_id="guild",
                discord_id="1",
                discord_name="Mary",
                real_name="Display",
                weighting=1.25,
            )
        )
        db.add(
            PlayerProfile(
                scope_key="user:owner",
                guild_id="other",
                discord_id="1",
                discord_name="Other",
                weighting=2.0,
            )
        )
        db.commit()
    discord = client.app.state.discord
    discord.poll_message.return_value = closing_message(finalized=False)
    assert client.post(path + "/close", headers=headers).status_code == 202
    with DBSession(client.app.state.engine) as db:
        assert db.get(PlayerProfile, ("user:owner", "guild", "1")).weighting == 1.25
    # The setting is captured at the start of this closure, just like input weights.
    client.put(
        "/api/settings/assignment",
        headers=headers,
        json={
            "automatic_weight_adjustment": not enabled,
            "announce_table_changes": False,
            "post_discord_updates_to_thread": False,
        },
    )
    discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    run = client.get(path + "/assignments").json()
    assert run["snapshot"]["automatic_weight_adjustment"] is enabled

    def current():
        with DBSession(client.app.state.engine) as db:
            return {
                p.discord_id: p.weighting
                for p in db.query(PlayerProfile).filter_by(guild_id="guild")
            }

    weights = current()
    for player in run["snapshot"]["players"]:
        original = 1.25 if player["id"] == "1" else 5.0
        if enabled:
            delta = -0.5 if player["id"] in run["result"]["assignments"] else 0.5
            assert weights[player["id"]] == pytest.approx(original + delta)
        elif player["id"] == "1":
            assert weights[player["id"]] == original
        else:
            assert player["id"] not in weights
    assert client.post(path + "/close", headers=headers).status_code == 200
    client.post(
        path + "/announcement/retry", headers=headers, json={"confirm_repost": False}
    )
    client.post(path + "/archive", headers=headers)
    assert current() == weights
    with DBSession(client.app.state.engine) as db:
        assert db.get(PlayerProfile, ("user:owner", "other", "1")).weighting == 2.0
        assert (
            db.get(AssignmentPreference, "user:other").automatic_weight_adjustment
            is not enabled
        )
        assert (
            db.get(PlayerProfile, ("user:owner", "guild", "1")).real_name == "Display"
        )


@pytest.mark.parametrize("player_id", ["999", "test-" + "a" * 24])
def test_add_known_player_after_assignment_updates_discord_without_redrawing(
    client, player_id
):
    from copy import deepcopy

    from app.discord.announcements import dispatch_due
    from app.models import Announcement, Event, LotteryRun, PlayerProfile

    headers, event, path, _ = closing_event(client)
    engine = client.app.state.engine
    discord = client.app.state.discord
    # This test exercises roster edits independently of separate change notices.
    client.put(
        "/api/settings/assignment",
        headers=headers,
        json={
            "automatic_weight_adjustment": True,
            "announce_table_changes": False,
            "post_discord_updates_to_thread": False,
        },
    )
    discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    with DBSession(engine) as db:
        run = db.get(LotteryRun, event["id"])
        saved_snapshot = deepcopy(run.snapshot)
        saved_result = deepcopy(run.result)
        db.add(
            PlayerProfile(
                scope_key="user:owner",
                guild_id="guild",
                discord_id=player_id,
                discord_name="Late Player",
                real_name="Late Display Name",
                is_test=player_id.startswith("test-"),
            )
        )
        db.commit()
    target = f"{path}/manager-players/{player_id}"
    body = {"table": "A", "name": "Untrusted client name"}
    assert client.put(target, json=body).status_code == 403
    assert (
        client.put(
            target, headers=headers, json={**body, "table": "missing"}
        ).status_code
        == 409
    )
    assert (
        client.put(
            f"{path}/manager-players/888", headers=headers, json=body
        ).status_code
        == 409
    )
    assert client.put(target, headers=headers, json=body).status_code == 200
    assert client.put(target, headers=headers, json=body).status_code == 409
    rows = client.get(path + "/signups").json()
    table = next(row for row in rows if row["name"] == "A")
    added = next(player for player in table["players"] if player["id"] == player_id)
    assert added["name"] == "Late Player"
    assert added["display_name"] == "Late Display Name"
    assert len(table["players"]) == 2
    with DBSession(engine) as db:
        run = db.get(LotteryRun, event["id"])
        assert run.snapshot == saved_snapshot
        assert run.result == saved_result
        refresh = (
            db.query(Announcement).filter_by(event_id=event["id"], kind="refresh").one()
        )
        assert refresh.state == "pending"
    dispatch_due(engine, lambda guild, channel: discord)
    channel, message, edit = discord.at.return_value.edit_announcement.call_args.args
    assert (channel, message) == ("channel", "announcement")
    field = next(
        field
        for field in edit["embeds"][0]["fields"]
        if field["name"].startswith("A (")
    )
    assert (
        "Late Player" if player_id.startswith("test-") else f"<@{player_id}>"
    ) in field["value"]
    assert client.delete(target, headers=headers).status_code == 200
    assert all(
        player["id"] != player_id
        for row in client.get(path + "/signups").json()
        for player in row["players"]
    )
    assert client.put(target, headers=headers, json=body).status_code == 409
    with DBSession(engine) as db:
        db.add(
            PlayerProfile(
                scope_key="user:owner",
                guild_id="guild",
                discord_id="777",
                discord_name="Other",
            )
        )
        db.get(Event, event["id"]).archived_at = time.time()
        db.commit()
    assert (
        client.put(
            f"{path}/manager-players/777", headers=headers, json=body
        ).status_code
        == 409
    )
