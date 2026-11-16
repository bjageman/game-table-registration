"""Final assignment notices share durable delivery and scoped opt-outs."""

import asyncio

import pytest
from flow_helpers import closing_event, closing_message
from promotion_helpers import discord_client
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_promotion_dm_gateway import interaction

from app.assignments.roster import build_current_roster
from app.config import Settings
from app.discord import promotion_dms
from app.discord.gateway import SignupGateway
from app.discord.seat_notifications import stop_notifications
from app.models import (
    AssignmentPreference,
    Event,
    LotteryRun,
    PlayerProfile,
    PromotionDM,
)


def queue(engine):
    with Session(engine) as db:
        event = db.get(Event, "event")
        event.location = "Game Store"
        promotion_dms.enqueue_assignments(db, event, db.get(LotteryRun, "event"))
        db.commit()
        return db.scalar(select(PromotionDM.id))


def test_content_buttons_delivery_and_no_duplicates(promotion_db):
    notice_id = queue(promotion_db)
    assert queue(promotion_db) == notice_id
    discord = discord_client()
    promotion_dms.dispatch_due(promotion_db, discord)
    promotion_dms.dispatch_due(promotion_db, discord)
    discord.open_dm.assert_called_once_with("1")
    discord.send_announcement.assert_called_once()
    with Session(promotion_db) as db:
        notice = db.get(PromotionDM, notice_id)
        assert notice.kind == "assignment"
        content = notice.payload["content"]
        assert (
            "Congratulations! You got assigned to **Table A** for **Game Night**"
            in content
        )
        assert "Time: <t:" in content
        assert "Location: Game Store" in content
        buttons = notice.payload["components"][0]["components"]
        assert [b["label"] for b in buttons] == [
            "Give up my seat",
            "Stop notifications",
        ]
        assert buttons[1]["custom_id"] == promotion_dms.STOP_PREFIX + notice.id


@pytest.mark.parametrize("review", [True, False])
def test_queue_only_after_finalization_and_only_seated_players(client, review):
    headers, _, path, _ = closing_event(client, review=review)
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    engine = client.app.state.engine
    if review:
        with Session(engine) as db:
            assert list(db.scalars(select(PromotionDM))) == []
        assert (
            client.post(path + "/assignments/approve", headers=headers).status_code
            == 200
        )
    with Session(engine) as db:
        notices = list(db.scalars(select(PromotionDM)))
        run = db.get(LotteryRun, path.split("/")[-1])
        assignments = build_current_roster(db, run)["assignments"]
        assert {n.discord_id: n.table_name for n in notices} == assignments
        assert all(n.kind == "assignment" for n in notices)
    client.post(path + "/assignments/approve", headers=headers)
    with Session(engine) as db:
        assert len(list(db.scalars(select(PromotionDM)))) == len(assignments)


@pytest.mark.parametrize("disabled", ["scope", "player", "test", "past"])
def test_disabled_or_ineligible_players_are_not_queued(promotion_db, disabled):
    with Session(promotion_db) as db:
        if disabled == "scope":
            db.get(AssignmentPreference, "user:owner").dm_assignments = False
        elif disabled == "past":
            db.get(Event, "event").starts_at = 0
        else:
            db.add(
                PlayerProfile(
                    scope_key="user:owner",
                    guild_id="guild",
                    discord_id="1",
                    seat_notifications=disabled != "player",
                    is_test=disabled == "test",
                )
            )
        db.commit()
    assert queue(promotion_db) is None


@pytest.mark.parametrize("disabled", ["scope", "player"])
def test_opt_out_after_queue_cancels_delivery(promotion_db, disabled):
    notice_id = queue(promotion_db)
    with Session(promotion_db) as db:
        if disabled == "scope":
            db.get(AssignmentPreference, "user:owner").dm_assignments = False
        else:
            db.add(
                PlayerProfile(
                    scope_key="user:owner",
                    guild_id="guild",
                    discord_id="1",
                    seat_notifications=False,
                )
            )
        db.commit()
    discord = discord_client()
    promotion_dms.dispatch_due(promotion_db, discord)
    discord.open_dm.assert_not_called()
    with Session(promotion_db) as db:
        assert db.get(PromotionDM, notice_id).state == "canceled"


def test_stop_button_is_scoped_idempotent_and_does_not_change_seat(promotion_db):
    notice_id = queue(promotion_db)
    promotion_dms.dispatch_due(promotion_db, discord_client())
    with Session(promotion_db) as db:
        db.add(
            PlayerProfile(
                scope_key="user:other",
                guild_id="guild",
                discord_id="1",
                seat_notifications=True,
            )
        )
        db.commit()
    for _ in range(2):
        assert "now off" in stop_notifications(
            promotion_db, notice_id, "1", "private-channel", "private-message"
        )
    with Session(promotion_db) as db:
        assert (
            db.get(PlayerProfile, ("user:owner", "guild", "1")).seat_notifications
            is False
        )
        assert (
            db.get(PlayerProfile, ("user:other", "guild", "1")).seat_notifications
            is True
        )
        assert build_current_roster(db, db.get(LotteryRun, "event"))["assignments"] == {
            "1": "Table A"
        }


@pytest.mark.parametrize("invalid", ["user", "channel", "message", "unsent"])
def test_stop_button_rejects_forged_notice_context(promotion_db, invalid):
    notice_id = queue(promotion_db)
    if invalid != "unsent":
        promotion_dms.dispatch_due(promotion_db, discord_client())
    result = stop_notifications(
        promotion_db,
        notice_id,
        "999" if invalid == "user" else "1",
        "wrong" if invalid == "channel" else "private-channel",
        "wrong" if invalid == "message" else "private-message",
    )
    assert "Something went wrong" in result
    with Session(promotion_db) as db:
        assert db.get(PlayerProfile, ("user:owner", "guild", "1")) is None


def test_assignment_notice_buttons_use_existing_gateway_security_and_withdrawal(
    promotion_db,
):
    notice_id = queue(promotion_db)
    promotion_dms.dispatch_due(promotion_db, discord_client())

    async def check():
        gateway = SignupGateway(
            promotion_db, Settings(_env_file=None, discord_client_id="123")
        )
        item = interaction(notice_id)
        item.user.id = 1
        item.data["custom_id"] = promotion_dms.STOP_PREFIX + notice_id
        await gateway.on_interaction(item)
        assert "now off" in item.edit_original_response.call_args.kwargs["content"]
        withdraw = interaction(notice_id)
        withdraw.user.id = 1
        await gateway.on_interaction(withdraw)
        assert (
            "You have withdrawn"
            in withdraw.edit_original_response.call_args.kwargs["content"]
        )
        await gateway.close()

    asyncio.run(check())
    with Session(promotion_db) as db:
        assert build_current_roster(db, db.get(LotteryRun, "event"))["assignments"] == {
            "2": "Table A"
        }


def test_profile_opt_out_visible_when_organization_notifications_disabled(client):
    from flow_helpers import login

    headers = login(client)
    client.app.state.discord.bot.return_value = {"username": "Alice"}
    settings = client.get("/api/settings/assignment").json()
    settings.update(dm_assignments=False, dm_waitlist_promotions=False)
    assert (
        client.put(
            "/api/settings/assignment", headers=headers, json=settings
        ).status_code
        == 200
    )
    assert client.get("/api/players/1").json()["seat_notifications"] is True
    assert (
        client.put("/api/players/1", json={"seat_notifications": False}).status_code
        == 403
    )
    response = client.put(
        "/api/players/1", headers=headers, json={"seat_notifications": False}
    )
    assert response.status_code == 200
    assert response.json()["seat_notifications"] is False
    assert client.get("/api/players/1").json()["seat_notifications"] is False
    # Unrelated edits by older clients must retain the player's preference.
    assert (
        client.put(
            "/api/players/1", headers=headers, json={"real_name": "Alice"}
        ).json()["seat_notifications"]
        is False
    )


@pytest.mark.parametrize("count", [1, 30])
def test_initial_notice_queries_are_batched(promotion_db, count):
    from test_roster_queries import recorded_queries

    people = [{"id": str(i), "name": f"Player {i}"} for i in range(1, count + 1)]
    with Session(promotion_db) as db:
        run = db.get(LotteryRun, "event")
        run.snapshot = {"players": people}
        run.result = {
            "assignments": {p["id"]: "Table A" for p in people},
            "waitlist": [],
            "tables": [{"name": "Table A", "players": people, "waitlist": []}],
        }
        db.commit()
    with Session(promotion_db) as db:
        event = db.get(Event, "event")
        run = db.get(LotteryRun, "event")
        with recorded_queries(promotion_db) as statements:
            promotion_dms.enqueue_assignments(db, event, run)
        assert len(statements) <= 8
        db.commit()
        assert len(list(db.scalars(select(PromotionDM)))) == count
