"""Saved draws cannot reach Discord until an authorized organizer approves."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest
from flow_helpers import closing_event, closing_message, set_assignment_review
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.announcements import dispatch_due
from app.closing import close_and_assign
from app.models import (
    Announcement,
    AssignmentPreference,
    Event,
    LotteryRun,
    PlayerProfile,
)


def prepared(client, *, default_scope=False):
    headers, event, path, _ = closing_event(client, review=True)
    if default_scope:
        with Session(client.app.state.engine) as db:
            db.execute(delete(AssignmentPreference))
            db.commit()
    client.app.state.discord.poll_message.return_value = closing_message()
    return headers, event, path


@pytest.mark.parametrize("automatic", [False, True])
def test_preview_survives_restart_without_publication_or_weight_changes(
    client, automatic
):
    headers, event, path = prepared(client, default_scope=True)
    engine = client.app.state.engine
    discord = client.app.state.discord
    if automatic:
        assert close_and_assign(engine, discord, event["id"], "system:auto", "channel")
        result = client.get("/api/events").json()[0]
    else:
        response = client.post(path + "/close", headers=headers)
        assert response.status_code == 200
        result = response.json()
    assert result["status"] == "review"
    saved = client.get(path + "/assignments").json()
    rows = client.get(path + "/signups").json()
    assert any(row["players"] for row in rows)
    assert any(row["waitlist"] for row in rows)
    with Session(engine) as db:
        assert db.get(LotteryRun, event["id"])
        assert list(db.scalars(select(Announcement))) == []
        assert list(db.scalars(select(PlayerProfile))) == []
    # Background dispatch and closing retries must not bypass the review.
    dispatch_due(engine, lambda guild, channel: discord)
    set_assignment_review(client, headers, False)
    assert client.post(path + "/close", headers=headers).json()["status"] == "review"
    assert client.get(path + "/assignments").json() == saved
    discord.send_announcement.assert_not_called()


def test_approval_publishes_exact_preview_and_adjusts_weights_once(client):
    headers, event, path = prepared(client)
    assert client.post(path + "/close", headers=headers).json()["status"] == "review"
    engine = client.app.state.engine
    with Session(engine) as db:
        run = db.get(LotteryRun, event["id"])
        preview = (run.seed, deepcopy(run.snapshot), deepcopy(run.result))
    target = path + "/assignments/approve"
    assert client.post(target).status_code == 403
    assert client.post(target, headers=headers).json()["status"] == "assigned"
    with Session(engine) as db:
        run = db.get(LotteryRun, event["id"])
        assert (run.seed, run.snapshot, run.result) == preview
        weights = {p.discord_id: p.weighting for p in db.scalars(select(PlayerProfile))}
        assert all(
            weight == (4.5 if player_id in run.result["assignments"] else 5.5)
            for player_id, weight in weights.items()
        )
        announcements = list(db.scalars(select(Announcement.id)))
        assert announcements
    assert client.post(target, headers=headers).json()["status"] == "assigned"
    with Session(engine) as db:
        assert {
            p.discord_id: p.weighting for p in db.scalars(select(PlayerProfile))
        } == weights
        assert list(db.scalars(select(Announcement.id))) == announcements


def test_approval_can_delete_signup_message_before_publishing(client):
    headers, event, path = prepared(client)
    assert client.post(path + "/close", headers=headers).json()["status"] == "review"

    approved = client.post(
        path + "/assignments/approve?delete_signup_message=true", headers=headers
    )

    assert approved.status_code == 200
    assert approved.json()["status"] == "assigned"
    client.app.state.discord.at.return_value.delete_poll.assert_called_once_with(
        "message"
    )


def test_review_blocks_mutations_and_public_bypasses(client):
    headers, event, path = prepared(client)
    event_id = event["id"]
    client.post(path + "/close", headers=headers)
    rows = client.get(path + "/signups").json()
    seated = next(p["id"] for row in rows for p in row["players"])
    waiting_table = next(row for row in rows if row["waitlist"])
    waiting = waiting_table["waitlist"][0]["id"]
    assert client.delete(path + f"/manager-players/{seated}", headers=headers).status_code == 200
    updated = client.get(path + "/signups").json()
    next_waiting = next(row for row in updated if row["waitlist"])
    waiting = next_waiting["waitlist"][0]["id"]
    assert client.post(
        path + f"/assigned-players/{waiting}",
        headers=headers,
        json={"table": next_waiting["name"]},
    ).status_code == 200
    assert next(row for row in client.get("/api/events").json() if row["id"] == event_id)["status"] == "review"
    assert (
        client.post(
            path + "/announcement/retry", headers=headers, json={"confirm_repost": True}
        ).status_code
        == 409
    )
    assert client.post(path + "/share", headers=headers).status_code == 409
    client.app.state.discord.send_announcement.assert_not_called()


def test_review_can_be_deleted_without_publishing_or_changing_weights(client):
    headers, event, path = prepared(client)
    assert client.post(path + "/close", headers=headers).json()["status"] == "review"
    assert client.delete(path, headers=headers).status_code == 204
    with Session(client.app.state.engine) as db:
        assert db.get(Event, event["id"]) is None
        assert db.get(LotteryRun, event["id"]) is None
        assert list(db.scalars(select(PlayerProfile))) == []
    client.app.state.discord.send_announcement.assert_not_called()


def test_approval_scope_and_missing_result_are_checked(client):
    headers, event, path = prepared(client)
    assert (
        client.post(path + "/assignments/approve", headers=headers).status_code == 409
    )
    client.post(path + "/close", headers=headers)
    engine = client.app.state.engine
    with Session(engine) as db:
        db.get(Event, event["id"]).created_by = "other"
        db.commit()
    assert (
        client.post(path + "/assignments/approve", headers=headers).status_code == 404
    )
    with Session(engine) as db:
        db.get(Event, event["id"]).created_by = "owner"
        db.execute(delete(LotteryRun).where(LotteryRun.event_id == event["id"]))
        db.commit()
    assert (
        client.post(path + "/assignments/approve", headers=headers).status_code == 503
    )
    client.app.state.discord.send_announcement.assert_not_called()


def test_concurrent_approvals_finalize_once(client):
    headers, _, path = prepared(client)
    client.post(path + "/close", headers=headers)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(
                lambda _: client.post(path + "/assignments/approve", headers=headers),
                range(2),
            )
        )
    assert all(response.status_code == 200 for response in responses)
    with Session(client.app.state.engine) as db:
        weights = [p.weighting for p in db.scalars(select(PlayerProfile))]
        assert all(weight in {4.5, 5.5} for weight in weights)
        assert len(list(db.scalars(select(Announcement)))) == 2


def test_review_preference_is_frozen_while_discord_finalizes(client):
    headers, _, path = prepared(client)
    discord = client.app.state.discord
    discord.poll_message.return_value = closing_message(finalized=False)
    assert client.post(path + "/close", headers=headers).status_code == 202
    set_assignment_review(client, headers, False)
    discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).json()["status"] == "review"
    discord.send_announcement.assert_not_called()


def test_review_can_be_disabled_for_immediate_publication(client):
    headers, _, path, _ = closing_event(client, review=False)
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).json()["status"] == "assigned"
    client.app.state.discord.send_announcement.assert_called()
