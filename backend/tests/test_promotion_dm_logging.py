"""Private seat-withdrawal failures are diagnosable without exposing DM contents."""

import logging

import pytest
from promotion_helpers import discord_client, queued
from sqlalchemy.orm import Session

from app.assignments.player_changes import withdraw_from_promotion_dm
from app.discord.promotion_dms import dispatch_due
from app.models import EventWithdrawal, PromotionDM


@pytest.mark.parametrize(
    "failure,reason",
    [
        ("missing", "notice_not_found"),
        ("recipient", "recipient_mismatch"),
        ("state", "notice_not_sent"),
        ("channel", "channel_mismatch"),
        ("message", "message_mismatch"),
    ],
)
def test_rejected_dm_logs_exact_reason_and_received_and_saved_ids(
    promotion_db, caplog, failure, reason
):
    notice_id = queued(promotion_db)
    dispatch_due(promotion_db, discord_client())
    with Session(promotion_db) as db:
        notice = db.get(PromotionDM, notice_id)
        notice.payload = {"content": "PRIVATE_CONTENT_DO_NOT_LOG"}
        if failure == "state":
            notice.state = "sending"
            notice.unknown = True
        db.commit()
    request_id = "missing-notice" if failure == "missing" else notice_id
    user = "other-user" if failure == "recipient" else "2"
    channel = "other-channel" if failure == "channel" else "private-channel"
    message = "other-message" if failure == "message" else "private-message"
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        response = withdraw_from_promotion_dm(
            promotion_db, request_id, user, channel, message
        )
    assert response == "Something went wrong. Please contact the host for assistance."
    assert f"reason={reason}" in caplog.text
    for field, value in (
        ("notice_id", request_id),
        ("user_id", user),
        ("channel_id", channel),
        ("message_id", message),
    ):
        assert f"{field}={value}" in caplog.text
    if failure != "missing":
        assert "event_id=event" in caplog.text
        assert "expected_user_id=2" in caplog.text
        assert "expected_channel_id=private-channel" in caplog.text
        assert "expected_message_id=private-message" in caplog.text
        assert "attempts=1" in caplog.text
    if failure == "state":
        assert "notice_state=sending" in caplog.text and "unknown=True" in caplog.text
    assert "PRIVATE_CONTENT_DO_NOT_LOG" not in caplog.text
    with Session(promotion_db) as db:
        assert db.get(EventWithdrawal, ("event", "2")) is None


def test_success_and_duplicate_click_have_distinct_log_outcomes(promotion_db, caplog):
    notice_id = queued(promotion_db)
    dispatch_due(promotion_db, discord_client())
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        response = withdraw_from_promotion_dm(
            promotion_db, notice_id, "2", "private-channel", "private-message"
        )
        assert "You have withdrawn" in response
        assert "Promotion DM withdrawal completed" in caplog.text
        caplog.clear()
        response = withdraw_from_promotion_dm(
            promotion_db, notice_id, "2", "private-channel", "private-message"
        )
        assert "no longer have a seat" in response
        assert "reason=no_current_seat" in caplog.text
        assert f"notice_id={notice_id}" in caplog.text
