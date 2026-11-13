"""Promotion delivery never changes seats or duplicates ambiguous sends."""

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event as ThreadEvent

import pytest
from promotion_helpers import discord_client, queued
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import promotion_dms, withdrawals
from app.discord_api import DiscordRequestError
from app.models import (
    AssignmentPreference,
    Event,
    EventWithdrawal,
    LotteryRun,
    PlayerProfile,
    PromotionDM,
)


def due_again(engine, notice_id):
    with Session(engine) as db:
        db.get(PromotionDM, notice_id).next_attempt = 0
        db.commit()


def test_default_off_and_simulated_players_are_not_notified(promotion_db):
    with Session(promotion_db) as db:
        event = db.get(Event, "event")
        preferences = db.get(AssignmentPreference, "user:owner")
        preferences.dm_waitlist_promotions = False
        promotion_dms.enqueue(db, event, "2", "Table A")
        preferences.dm_waitlist_promotions = True
        promotion_dms.enqueue(db, event, "test-2", "Table A")
        db.commit()
        assert list(db.scalars(select(PromotionDM))) == []


@pytest.mark.parametrize("source", ["manager_remove", "reaction", "manager_add"])
def test_all_waitlist_promotions_queue_one_notice_independent_of_public_settings(
    promotion_db, source
):
    with Session(promotion_db) as db:
        saved = db.get(LotteryRun, "event").result
    if source == "manager_remove":
        assert withdrawals.manager_remove(promotion_db, "guild", "event", "1")
        assert not withdrawals.manager_remove(promotion_db, "guild", "event", "1")
    elif source == "reaction":
        assert withdrawals.withdraw(
            promotion_db, "guild", "channel", "assignment-message", "1"
        )
        assert not withdrawals.withdraw(
            promotion_db, "guild", "channel", "assignment-message", "1"
        )
    else:
        assert withdrawals.manager_add(promotion_db, "guild", "event", "2", "Table A")
        assert not withdrawals.manager_add(
            promotion_db, "guild", "event", "2", "Table A"
        )
    with Session(promotion_db) as db:
        notices = list(db.scalars(select(PromotionDM)))
        assert len(notices) == 1
        assert notices[0].discord_id == "2"
        assert "Congratulations!" in notices[0].payload["content"]
        assert "Table A" in notices[0].payload["content"]
        button = notices[0].payload["components"][0]["components"][0]
        assert button["custom_id"] == promotion_dms.BUTTON_PREFIX + notices[0].id
        assert len(button["custom_id"]) <= 100
        assert db.get(LotteryRun, "event").result == saved
        assert (
            db.get(AssignmentPreference, "user:owner").announce_table_changes is False
        )


def test_adding_a_known_player_who_was_not_waitlisted_does_not_queue_a_dm(promotion_db):
    with Session(promotion_db) as db:
        db.add(
            PlayerProfile(
                guild_id="guild", discord_id="4", discord_name="Dan", weighting=5
            )
        )
        db.commit()
    assert withdrawals.manager_add(
        promotion_db, "guild", "event", "4", "Table A", allow_known_player=True
    )
    with Session(promotion_db) as db:
        assert list(db.scalars(select(PromotionDM))) == []


def test_delivery_is_durable_and_only_sends_once(promotion_db):
    notice_id = queued(promotion_db)
    discord = discord_client()
    promotion_dms.dispatch_due(promotion_db, discord)
    promotion_dms.dispatch_due(promotion_db, discord)
    discord.open_dm.assert_called_once_with("2")
    discord.send_announcement.assert_called_once()
    channel, body = discord.send_announcement.call_args.args
    assert channel == "private-channel"
    assert body["allowed_mentions"] == {"parse": [], "users": []}
    with Session(promotion_db) as db:
        notice = db.get(PromotionDM, notice_id)
        assert (notice.state, notice.message_id, notice.channel_id) == (
            "sent",
            "private-message",
            "private-channel",
        )
        assert withdrawals.current_result(db, db.get(LotteryRun, "event"))[
            "assignments"
        ] == {"2": "Table A"}


@pytest.mark.parametrize("stage", ["open", "send"])
def test_closed_inbox_is_terminal_and_keeps_the_promoted_seat(promotion_db, stage):
    notice_id = queued(promotion_db)
    discord = discord_client()
    (
        discord.open_dm if stage == "open" else discord.send_announcement
    ).side_effect = DiscordRequestError(403)
    promotion_dms.dispatch_due(promotion_db, discord)
    promotion_dms.dispatch_due(promotion_db, discord)
    with Session(promotion_db) as db:
        assert db.get(PromotionDM, notice_id).state == "blocked"
        assert (
            withdrawals.current_result(db, db.get(LotteryRun, "event"))["assignments"][
                "2"
            ]
            == "Table A"
        )
    assert discord.open_dm.call_count == 1


def test_rate_limited_send_retries_after_discord_delay(promotion_db):
    notice_id = queued(promotion_db)
    discord = discord_client()
    discord.send_announcement.side_effect = [
        DiscordRequestError(429, 90),
        {"id": "sent"},
    ]
    before = time.time()
    promotion_dms.dispatch_due(promotion_db, discord)
    with Session(promotion_db) as db:
        notice = db.get(PromotionDM, notice_id)
        assert notice.state == "pending"
        assert notice.unknown is False
        assert notice.next_attempt >= before + 90
    promotion_dms.dispatch_due(promotion_db, discord)
    assert discord.send_announcement.call_count == 1
    due_again(promotion_db, notice_id)
    promotion_dms.dispatch_due(promotion_db, discord)
    assert discord.send_announcement.call_count == 2
    discord.open_dm.assert_called_once()


@pytest.mark.parametrize("found", [None, "recovered-message"])
def test_ambiguous_send_is_reconciled_without_blind_repost(promotion_db, found):
    notice_id = queued(promotion_db)
    discord = discord_client()
    discord.send_announcement.side_effect = DiscordRequestError(None)
    promotion_dms.dispatch_due(promotion_db, discord)
    due_again(promotion_db, notice_id)
    discord.find_announcement.return_value = found
    promotion_dms.dispatch_due(promotion_db, discord)
    discord.send_announcement.assert_called_once()
    with Session(promotion_db) as db:
        notice = db.get(PromotionDM, notice_id)
        assert notice.state == ("sent" if found else "needs_review")
        assert notice.message_id == found


@pytest.mark.parametrize("condition", ["disabled", "archived", "started", "withdrawn"])
def test_obsolete_notifications_are_not_sent(promotion_db, condition):
    notice_id = queued(promotion_db)
    with Session(promotion_db) as db:
        if condition == "disabled":
            db.get(AssignmentPreference, "user:owner").dm_waitlist_promotions = False
        elif condition == "archived":
            db.get(Event, "event").archived_at = time.time()
        elif condition == "started":
            db.get(Event, "event").starts_at = time.time() - 1
        else:
            db.add(
                EventWithdrawal(
                    event_id="event",
                    discord_id="2",
                    table_name="Table A",
                    withdrawn_at=time.time(),
                )
            )
        db.commit()
    discord = discord_client()
    promotion_dms.dispatch_due(promotion_db, discord)
    discord.open_dm.assert_not_called()
    with Session(promotion_db) as db:
        assert db.get(PromotionDM, notice_id).state == "canceled"


def test_concurrent_deliverers_only_send_once(promotion_db):
    notice_id = queued(promotion_db)
    discord = discord_client()
    started, release = ThreadEvent(), ThreadEvent()

    def send(*_args):
        started.set()
        assert release.wait(5)
        return {"id": "private-message"}

    discord.send_announcement.side_effect = send
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(promotion_dms.deliver, promotion_db, discord, notice_id)
        assert started.wait(5)
        try:
            second = pool.submit(
                promotion_dms.deliver, promotion_db, discord, notice_id
            )
            second.result(timeout=5)
        finally:
            release.set()
        first.result(timeout=5)
    discord.send_announcement.assert_called_once()


def test_recipient_can_withdraw_and_next_waitlisted_player_gets_notified_once(
    promotion_db,
):
    notice_id = queued(promotion_db)
    discord = discord_client()
    promotion_dms.dispatch_due(promotion_db, discord)
    with Session(promotion_db) as db:
        snapshot = db.get(LotteryRun, "event").snapshot
    result = promotion_dms.withdraw(
        promotion_db, notice_id, "2", "private-channel", "private-message"
    )
    assert "You have withdrawn" in result
    assert "no longer have a seat" in promotion_dms.withdraw(
        promotion_db, notice_id, "2", "private-channel", "private-message"
    )
    with Session(promotion_db) as db:
        assert withdrawals.current_result(db, db.get(LotteryRun, "event"))[
            "assignments"
        ] == {"3": "Table A"}
        assert len(list(db.scalars(select(PromotionDM)))) == 2
        assert db.get(LotteryRun, "event").snapshot == snapshot


@pytest.mark.parametrize(
    "user,channel,message",
    [
        ("3", "private-channel", "private-message"),
        ("2", "other", "private-message"),
        ("2", "private-channel", "other"),
    ],
)
def test_forged_private_controls_cannot_change_a_seat(
    promotion_db, user, channel, message
):
    notice_id = queued(promotion_db)
    promotion_dms.dispatch_due(promotion_db, discord_client())
    assert "cannot be used" in promotion_dms.withdraw(
        promotion_db, notice_id, user, channel, message
    )
    with Session(promotion_db) as db:
        assert db.get(EventWithdrawal, ("event", "2")) is None


@pytest.mark.parametrize("expired", [False, True])
def test_archived_or_started_event_rejects_dm_withdrawal(promotion_db, expired):
    notice_id = queued(promotion_db)
    promotion_dms.dispatch_due(promotion_db, discord_client())
    with Session(promotion_db) as db:
        event = db.get(Event, "event")
        if expired:
            event.starts_at = time.time() - 1
        else:
            event.archived_at = time.time()
        db.commit()
    assert "no longer accepting" in promotion_dms.withdraw(
        promotion_db, notice_id, "2", "private-channel", "private-message"
    )
    with Session(promotion_db) as db:
        assert db.get(EventWithdrawal, ("event", "2")) is None


def test_concurrent_dm_withdrawals_release_only_one_seat(promotion_db):
    notice_id = queued(promotion_db)
    promotion_dms.dispatch_due(promotion_db, discord_client())
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                promotion_dms.withdraw,
                promotion_db,
                notice_id,
                "2",
                "private-channel",
                "private-message",
            )
            for _ in range(2)
        ]
        results = [future.result(timeout=10) for future in futures]
    assert sum("You have withdrawn" in result for result in results) == 1
    with Session(promotion_db) as db:
        assert withdrawals.current_result(db, db.get(LotteryRun, "event"))[
            "assignments"
        ] == {"3": "Table A"}
        assert len(list(db.scalars(select(PromotionDM)))) == 2


def test_manual_add_to_another_table_still_notifies_a_globally_waitlisted_player(
    promotion_db,
):
    with Session(promotion_db) as db:
        event = db.get(Event, "event")
        event.tables = [*event.tables, {"name": "Table B", "capacity": 1}]
        run = db.get(LotteryRun, "event")
        run.result = {
            **run.result,
            "tables": [
                *run.result["tables"],
                {"name": "Table B", "players": [], "waitlist": []},
            ],
        }
        db.add(
            PlayerProfile(
                guild_id="guild", discord_id="2", discord_name="Bob", weighting=5
            )
        )
        db.commit()
    assert withdrawals.manager_add(
        promotion_db, "guild", "event", "2", "Table B", allow_known_player=True
    )
    with Session(promotion_db) as db:
        notice = db.scalar(select(PromotionDM))
        assert notice.discord_id == "2"
        assert notice.table_name == "Table B"


def test_one_closed_inbox_does_not_block_another_private_notice(promotion_db):
    assert withdrawals.manager_add(promotion_db, "guild", "event", "2", "Table A")
    assert withdrawals.manager_add(promotion_db, "guild", "event", "3", "Table A")
    discord = discord_client()
    discord.open_dm.side_effect = [DiscordRequestError(403), "another-private-channel"]
    promotion_dms.dispatch_due(promotion_db, discord)
    with Session(promotion_db) as db:
        assert {
            row.discord_id: row.state for row in db.scalars(select(PromotionDM))
        } == {"2": "blocked", "3": "sent"}
    discord.send_announcement.assert_called_once()


def test_expired_worker_lease_recovers_delivery_after_restart(promotion_db):
    notice_id = queued(promotion_db)
    with Session(promotion_db) as db:
        notice = db.get(PromotionDM, notice_id)
        notice.state = "sending"
        notice.token = "interrupted-worker"
        notice.lease_until = time.time() - 1
        notice.channel_id = "private-channel"
        notice.attempted_at = time.time() - 30
        db.commit()
    discord = discord_client()
    discord.find_announcement.return_value = "recovered-message"
    promotion_dms.dispatch_due(promotion_db, discord)
    discord.send_announcement.assert_not_called()
    discord.open_dm.assert_not_called()
    with Session(promotion_db) as db:
        assert db.get(PromotionDM, notice_id).state == "sent"
        assert db.get(PromotionDM, notice_id).message_id == "recovered-message"


def test_dm_withdrawal_from_an_overfilled_table_does_not_promote_another_player(
    promotion_db,
):
    assert withdrawals.manager_add(promotion_db, "guild", "event", "2", "Table A")
    with Session(promotion_db) as db:
        notice_id = db.scalar(select(PromotionDM.id))
    promotion_dms.dispatch_due(promotion_db, discord_client())
    assert "You have withdrawn" in promotion_dms.withdraw(
        promotion_db, notice_id, "2", "private-channel", "private-message"
    )
    with Session(promotion_db) as db:
        current = withdrawals.current_result(db, db.get(LotteryRun, "event"))
        assert current["assignments"] == {"1": "Table A"}
        assert current["waitlist"] == ["3"]
        assert db.get(EventWithdrawal, ("event", "2")).promoted_id is None
        assert len(list(db.scalars(select(PromotionDM)))) == 1
