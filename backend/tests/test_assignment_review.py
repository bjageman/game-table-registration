"""Saved draws cannot reach Discord until an authorized organizer approves."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest
from flow_helpers import closing_event, closing_message, set_assignment_review
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.assignments.closing import close_and_assign
from app.assignments.withdrawals import current_result
from app.discord.announcements import dispatch_due, payloads
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
        announcements = set(db.scalars(select(Announcement.id)))
        assert announcements
    assert client.post(target, headers=headers).json()["status"] == "assigned"
    with Session(engine) as db:
        assert {
            p.discord_id: p.weighting for p in db.scalars(select(PlayerProfile))
        } == weights
        assert set(db.scalars(select(Announcement.id))) == announcements


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


def test_approval_posts_edited_assignments_and_waitlists(client):
    headers, event, path = prepared(client)
    client.post(path + "/close", headers=headers)
    engine = client.app.state.engine
    with Session(engine) as db:
        original = deepcopy(db.get(LotteryRun, event["id"]).result)
    removed = next(iter(original["assignments"]))
    assert (
        client.delete(path + f"/manager-players/{removed}", headers=headers).status_code
        == 200
    )
    assert (
        client.post(
            path + f"/waitlisted-players/{removed}",
            headers=headers,
            json={"table": "B"},
        ).status_code
        == 200
    )
    rows = client.get(path + "/signups").json()
    waiting_table = next(
        row
        for row in rows
        if any(player["id"] != removed for player in row["waitlist"])
    )
    waiting = next(
        player["id"] for player in waiting_table["waitlist"] if player["id"] != removed
    )
    assert (
        client.post(
            path + f"/assigned-players/{waiting}",
            headers=headers,
            json={"table": waiting_table["name"]},
        ).status_code
        == 200
    )
    with Session(engine) as db:
        run = db.get(LotteryRun, event["id"])
        edited = deepcopy(current_result(db, run))
        expected = payloads(db.get(Event, event["id"]), "channel", edited, run.snapshot)
        assert edited != original
    assert (
        client.post(path + "/assignments/approve", headers=headers).status_code == 200
    )
    with Session(engine) as db:
        posts = list(
            db.scalars(
                select(Announcement)
                .where(
                    Announcement.event_id == event["id"],
                    Announcement.kind == "assignment",
                )
                .order_by(Announcement.part)
            )
        )
        assert [post.payload for post in posts] == expected
        run = db.get(LotteryRun, event["id"])
        assert run.result == original
        assert current_result(db, run) == edited
        # Legacy events without announcement records must also use edited rosters.
        db.execute(delete(Announcement).where(Announcement.event_id == event["id"]))
        db.commit()
    assert (
        client.post(
            path + "/announcement/retry", headers=headers, json={"confirm_repost": True}
        ).status_code
        == 200
    )
    with Session(engine) as db:
        posts = list(
            db.scalars(
                select(Announcement)
                .where(
                    Announcement.event_id == event["id"],
                    Announcement.kind == "assignment",
                )
                .order_by(Announcement.part)
            )
        )
        assert [post.payload for post in posts] == expected


def test_review_blocks_mutations_and_public_bypasses(client):
    headers, event, path = prepared(client)
    event_id = event["id"]
    client.post(path + "/close", headers=headers)
    rows = client.get(path + "/signups").json()
    seated = next(p["id"] for row in rows for p in row["players"])
    waiting_table = next(row for row in rows if row["waitlist"])
    waiting = waiting_table["waitlist"][0]["id"]
    assert (
        client.delete(path + f"/manager-players/{seated}", headers=headers).status_code
        == 200
    )
    updated = client.get(path + "/signups").json()
    next_waiting = next(row for row in updated if row["waitlist"])
    waiting = next_waiting["waitlist"][0]["id"]
    assert (
        client.post(
            path + f"/assigned-players/{waiting}",
            headers=headers,
            json={"table": next_waiting["name"]},
        ).status_code
        == 200
    )
    assert (
        next(row for row in client.get("/api/events").json() if row["id"] == event_id)[
            "status"
        ]
        == "review"
    )
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


def test_rejected_approval_stays_in_review_and_can_retry(client):
    from app.discord.discord_api import DiscordRequestError

    headers, event, path = prepared(client)
    client.post(path + "/close", headers=headers)
    discord = client.app.state.discord
    discord.send_announcement.side_effect = DiscordRequestError(400)
    response = client.post(path + "/assignments/approve", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "review"
    assert response.json()["assignment_publication_pending"] is True
    assert response.json()["assignment_publication_error"]
    with Session(client.app.state.engine) as db:
        assert not list(db.scalars(select(PlayerProfile)))
        run = db.get(LotteryRun, event["id"])
        player = next(iter(run.result["assignments"]))
        table = run.result["assignments"][player]
    assert (
        client.delete(
            path + f"/manager-players/{player}",
            headers=headers,
            params={"table": table},
        ).status_code
        == 409
    )
    discord.send_announcement.side_effect = None
    response = client.post(path + "/assignments/approve", headers=headers)
    assert response.json()["status"] == "assigned"
    with Session(client.app.state.engine) as db:
        assert (
            len(
                list(
                    db.scalars(
                        select(Announcement).where(Announcement.kind == "assignment")
                    )
                )
            )
            == 1
        )
        assert all(p.weighting in (4.5, 5.5) for p in db.scalars(select(PlayerProfile)))


def test_partial_publication_does_not_advance_or_repeat_delivered_parts(client):
    from unittest.mock import patch

    from app.discord.discord_api import DiscordRequestError

    headers, event, path = prepared(client)
    client.post(path + "/close", headers=headers)
    discord = client.app.state.discord
    discord.send_announcement.side_effect = [{"id": "first"}, DiscordRequestError(400)]
    with patch(
        "app.discord.announcements.payloads",
        return_value=[{"content": "First roster"}, {"content": "Second roster"}],
    ):
        response = client.post(path + "/assignments/approve", headers=headers)
    assert response.json()["status"] == "review"
    with Session(client.app.state.engine) as db:
        assert not list(db.scalars(select(PlayerProfile)))
    discord.send_announcement.side_effect = None
    discord.send_announcement.return_value = {"id": "second"}
    assert (
        client.post(path + "/assignments/approve", headers=headers).json()["status"]
        == "assigned"
    )
    sent_contents = [
        call.args[1]["content"] for call in discord.send_announcement.call_args_list
    ]
    assert sent_contents.count("First roster") == 1
    assert sent_contents.count("Second roster") == 2


def test_background_confirmation_advances_review_without_reposting(client):
    from app.discord.discord_api import DiscordRequestError

    headers, event, path = prepared(client)
    client.post(path + "/close", headers=headers)
    discord = client.app.state.discord
    discord.send_announcement.side_effect = DiscordRequestError(None)
    assert (
        client.post(path + "/assignments/approve", headers=headers).json()["status"]
        == "review"
    )
    with Session(client.app.state.engine) as db:
        row = db.scalar(
            select(Announcement).where(
                Announcement.event_id == event["id"], Announcement.kind == "assignment"
            )
        )
        assert row.unknown is True
        row.next_attempt = 0
        db.commit()
    discord.send_announcement.side_effect = None
    discord.find_announcement.return_value = "already-posted"
    dispatch_due(client.app.state.engine, lambda guild, channel: discord)
    with Session(client.app.state.engine) as db:
        assert db.get(Event, event["id"]).status == "assigned"
        row = db.scalar(
            select(Announcement).where(
                Announcement.event_id == event["id"], Announcement.kind == "assignment"
            )
        )
        assert row.message_id == "already-posted"
    discord.find_announcement.assert_called_once()
    # The only POST attempt was the original ambiguous request.
    assignment_posts = [
        call
        for call in discord.send_announcement.call_args_list
        if call.args[1].get("embeds")
    ]
    assert len(assignment_posts) == 1


@pytest.mark.parametrize("review", [True, False])
def test_mixed_real_and_manual_test_players_publish_in_both_modes(client, review):
    from app.models import EventPlayerSetting

    headers, event, path, _ = closing_event(client, review=review)
    pid = "test-" + "c" * 24
    with Session(client.app.state.engine) as db:
        db.add(
            PlayerProfile(
                scope_key="user:owner",
                guild_id="guild",
                discord_id=pid,
                discord_name="Test Player 003",
                is_test=True,
            )
        )
        db.add(
            EventPlayerSetting(
                event_id=event["id"], discord_id=pid, guaranteed_table="A"
            )
        )
        db.commit()
    assert (
        client.put(
            path + f"/manager-players/{pid}",
            headers=headers,
            json={"table": "A", "name": "Test Player 003"},
        ).status_code
        == 200
    )
    discord = client.app.state.discord
    discord.poll_message.return_value = closing_message()
    discord.table_signups.return_value = [
        {"name": name, "players": []} for name in ("A", "B")
    ]
    closed = client.post(path + "/close", headers=headers)
    assert closed.status_code == 200
    if review:
        assert closed.json()["status"] == "review"
        assert (
            client.post(path + "/assignments/approve", headers=headers).json()["status"]
            == "assigned"
        )
    else:
        assert closed.json()["status"] == "assigned"
    sent = [
        call.args[1]
        for call in discord.send_announcement.call_args_list
        if call.args[1].get("embeds")
    ]
    assert sent
    assert any(
        "Test Player 003" in field["value"]
        for payload in sent
        for embed in payload["embeds"]
        for field in embed["fields"]
    )
    assert all(
        user.isdecimal()
        for payload in sent
        for user in payload["allowed_mentions"]["users"]
    )
    assert all("<@test-" not in payload["content"] for payload in sent)
