"""Waitlists earn a profile guarantee that is consumed by a subsequent seat."""

import time

import pytest
from flow_helpers import closing_event, closing_message
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assignments.player_changes import (
    add_player_to_waitlist,
    assign_player_to_table,
    remove_player_from_roster,
)
from app.assignments.swaps import swap_players
from app.assignments.waitlist_guarantees import finalize_guarantees
from app.models import AssignmentPreference, Event, LotteryRun, PlayerProfile
from app.schemas import SwapPlayersInput


def enable(engine, enabled=True, hours=5, starts_at=None):
    with Session(engine) as db:
        settings = db.get(AssignmentPreference, "user:owner")
        settings.guarantee_waitlisted_players = enabled
        settings.waitlist_guarantee_retention_hours = hours
        db.get(Event, "event").starts_at = starts_at or time.time() + 10 * 3600
        db.commit()


def finish(engine):
    with Session(engine) as db:
        finalize_guarantees(db, db.get(Event, "event"), db.get(LotteryRun, "event"))
        db.commit()


def flags(engine):
    with Session(engine) as db:
        return {
            p.discord_id: p.guaranteed_seat
            for p in db.scalars(
                select(PlayerProfile).where(PlayerProfile.scope_key == "user:owner")
            )
        }


def test_final_results_grant_waitlisted_and_clear_manual_guarantees(promotion_db):
    enable(promotion_db)
    with Session(promotion_db) as db:
        db.add(
            PlayerProfile(
                scope_key="user:owner",
                guild_id="guild",
                discord_id="1",
                guaranteed_seat=True,
            )
        )
        db.commit()
    finish(promotion_db)
    assert flags(promotion_db) == {"1": False, "2": True, "3": True}
    with Session(promotion_db) as db:
        assert db.get(PlayerProfile, ("user:owner", "guild", "2")).discord_name == "Bob"


def test_disabled_feature_leaves_profiles_untouched(promotion_db):
    enable(promotion_db, False)
    with Session(promotion_db) as db:
        db.add(
            PlayerProfile(
                scope_key="user:owner",
                guild_id="guild",
                discord_id="1",
                guaranteed_seat=True,
            )
        )
        db.commit()
    finish(promotion_db)
    assert flags(promotion_db) == {"1": True}


@pytest.mark.parametrize("method", ["automatic", "manual", "swap"])
@pytest.mark.parametrize("hours_before,keep", [(6, False), (5, True), (4, True)])
def test_promotion_cutoff_is_shared_by_all_seating_paths(
    promotion_db, monkeypatch, method, hours_before, keep
):
    enable(promotion_db, starts_at=100000 + hours_before * 3600)
    finish(promotion_db)
    monkeypatch.setattr("time.time", lambda: 100000)
    if method == "automatic":
        assert remove_player_from_roster(promotion_db, "guild", "event", "1")
    elif method == "manual":
        assert assign_player_to_table(promotion_db, "guild", "event", "2", "Table A")
    else:
        assert swap_players(
            promotion_db,
            "guild",
            "event",
            SwapPlayersInput(
                player_id="1",
                table="Table A",
                other_player_id="2",
                other_table="Table A",
                other_waitlist=True,
            ),
        )
        assert flags(promotion_db)["1"] is True
    assert flags(promotion_db)["2"] is keep
    assert flags(promotion_db)["3"] is True


def test_child_option_disables_late_exception(promotion_db, monkeypatch):
    enable(promotion_db, starts_at=100000 + 3600)
    with Session(promotion_db) as db:
        db.get(
            AssignmentPreference, "user:owner"
        ).keep_waitlist_guarantee_on_short_notice = False
        db.commit()
    finish(promotion_db)
    monkeypatch.setattr("time.time", lambda: 100000)
    assert assign_player_to_table(promotion_db, "guild", "event", "2", "Table A")
    assert flags(promotion_db)["2"] is False


def test_late_waitlist_additions_get_guarantees(promotion_db):
    enable(promotion_db)
    with Session(promotion_db) as db:
        db.add(
            PlayerProfile(
                scope_key="user:owner",
                guild_id="guild",
                discord_id="4",
                discord_name="Dan",
            )
        )
        db.commit()
    assert add_player_to_waitlist(promotion_db, "guild", "event", "4", "Table A")
    assert flags(promotion_db)["4"] is True


def test_review_has_no_profile_effect_until_approved(client):
    headers, event, path, _ = closing_event(client, review=True)
    settings = client.get("/api/settings/assignment").json()
    settings["guarantee_waitlisted_players"] = True
    assert (
        client.put(
            "/api/settings/assignment", headers=headers, json=settings
        ).status_code
        == 200
    )
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).json()["status"] == "review"
    engine = client.app.state.engine
    assert not any(flags(engine).values())
    assert (
        client.post(path + "/assignments/approve", headers=headers).json()["status"]
        == "assigned"
    )
    rows = client.get(path + "/signups").json()
    waiting = {p["id"] for row in rows for p in row["waitlist"]}
    profiles = flags(engine)
    assert waiting
    assert {pid for pid, guaranteed in profiles.items() if guaranteed} == waiting


def test_guarantees_are_consumed_in_another_event_only_in_same_organization(
    promotion_db,
):
    from app.models import Organization

    with Session(promotion_db) as db:
        db.add_all(
            [
                Organization(
                    id="one",
                    name="One",
                    normalized_name="one",
                    created_by="owner",
                    guild_id="guild",
                    channel_id="channel",
                ),
                Organization(
                    id="two",
                    name="Two",
                    normalized_name="two",
                    created_by="owner",
                    guild_id="guild",
                    channel_id="channel",
                ),
            ]
        )
        db.flush()
        db.get(Event, "event").organization_id = "one"
        db.add(
            AssignmentPreference(scope_key="org:one", guarantee_waitlisted_players=True)
        )
        db.add(
            PlayerProfile(
                scope_key="org:two",
                guild_id="guild",
                discord_id="2",
                guaranteed_seat=True,
            )
        )
        db.commit()
    finish(promotion_db)
    with Session(promotion_db) as db:
        assert db.get(PlayerProfile, ("org:one", "guild", "2")).guaranteed_seat is True
        db.add(
            Event(
                id="next",
                guild_id="guild",
                organization_id="one",
                title="Different event",
                starts_at=time.time() + 86400,
                duration_hours=24,
                tables=[{"name": "Other table", "capacity": 1}],
                created_by="owner",
            )
        )
        db.flush()
        run = LotteryRun(
            event_id="next",
            version="test",
            seed="seed",
            created_by="owner",
            created_at=time.time(),
            snapshot={"players": [{"id": "2", "name": "Bob"}]},
            result={
                "assignments": {"2": "Other table"},
                "waitlist": [],
                "tables": [
                    {
                        "name": "Other table",
                        "players": [{"id": "2", "name": "Bob"}],
                        "waitlist": [],
                    }
                ],
            },
        )
        db.add(run)
        db.flush()
        finalize_guarantees(db, db.get(Event, "next"), run)
        db.commit()
        assert db.get(PlayerProfile, ("org:one", "guild", "2")).guaranteed_seat is False
        assert db.get(PlayerProfile, ("org:one", "guild", "3")).guaranteed_seat is True
        assert db.get(PlayerProfile, ("org:two", "guild", "2")).guaranteed_seat is True


def test_review_promotions_use_seating_time_instead_of_approval_time(promotion_db):
    from app.assignments.placement_records import record_manual_assignment

    enable(promotion_db, starts_at=time.time() + 4 * 3600)
    with Session(promotion_db) as db:
        record_manual_assignment(db, "event", "2", "Table A", time.time() - 2 * 3600)
        db.commit()
    finish(promotion_db)
    assert flags(promotion_db)["2"] is False
    assert flags(promotion_db)["3"] is True


def test_enable_existing_waitlists_and_preserve_omitted_settings(
    client,
):
    headers, _, path, _ = closing_event(client)
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    rows = client.get(path + "/signups").json()
    waiting = {p["id"] for row in rows for p in row["waitlist"]}
    assert waiting
    settings = client.get("/api/settings/assignment").json()
    settings.update(
        guarantee_waitlisted_players=True, waitlist_guarantee_retention_hours=2
    )
    assert (
        client.put(
            "/api/settings/assignment", headers=headers, json=settings
        ).status_code
        == 200
    )
    assert {
        pid for pid, guaranteed in flags(client.app.state.engine).items() if guaranteed
    } == waiting
    saved = client.put(
        "/api/settings/assignment",
        headers=headers,
        json={"automatic_weight_adjustment": True, "announce_table_changes": True},
    )
    assert saved.json()["guarantee_waitlisted_players"] is True
    assert saved.json()["waitlist_guarantee_retention_hours"] == 2


@pytest.mark.parametrize("hours", [-1, 0, 1.5, 769])
def test_invalid_retention_window_rejected(client, hours):
    from flow_helpers import login

    headers = login(client)
    settings = client.get("/api/settings/assignment").json()
    settings["waitlist_guarantee_retention_hours"] = hours
    assert (
        client.put(
            "/api/settings/assignment", headers=headers, json=settings
        ).status_code
        == 422
    )


def test_next_draw_uses_and_consumes_the_waitlisted_profile_guarantee(client):
    from datetime import UTC, datetime, timedelta

    headers, _, first_path, _ = closing_event(client)
    settings = client.get("/api/settings/assignment").json()
    settings["guarantee_waitlisted_players"] = True
    client.put("/api/settings/assignment", headers=headers, json=settings)
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(first_path + "/close", headers=headers).status_code == 200
    rows = client.get(first_path + "/signups").json()
    player = next(p for row in rows for p in row["waitlist"])
    assert flags(client.app.state.engine)[player["id"]] is True
    discord = client.app.state.discord
    answer = {"answer_id": 9, "poll_media": {"text": "Next · 1 seats"}}
    discord.publish.return_value["poll"]["answers"] = [answer]
    discord.voter_users.side_effect = None
    discord.voter_users.return_value = [
        {"id": player["id"], "username": player["name"]},
        {"id": "999", "username": "Other player"},
    ]
    discord.table_signups.return_value = [
        {
            "name": "Next",
            "players": [
                {"id": player["id"], "name": player["name"]},
                {"id": "999", "name": "Other player"},
            ],
        }
    ]
    message = closing_message()
    message["poll"]["answers"] = [answer]
    message["poll"]["results"]["answer_counts"] = [{"id": 9, "count": 2}]
    discord.poll_message.return_value = message
    event = client.post(
        "/api/events",
        headers=headers,
        json={
            "title": "Different next event",
            "starts_at": (datetime.now(UTC) + timedelta(days=14)).isoformat(),
            "duration_hours": 24,
            "tables": [{"name": "Next", "capacity": 1}],
        },
    ).json()
    path = f"/api/events/{event['id']}"
    assert client.post(path + "/publish", headers=headers).status_code == 200
    assert client.post(path + "/close", headers=headers).status_code == 200
    with Session(client.app.state.engine) as db:
        run = db.get(LotteryRun, event["id"])
        assert run.result["assignments"] == {player["id"]: "Next"}
        assert (
            next(p for p in run.snapshot["players"] if p["id"] == player["id"])[
                "guaranteed_seat"
            ]
            is True
        )
    assert flags(client.app.state.engine)[player["id"]] is False
