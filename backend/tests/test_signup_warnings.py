"""Scheduled closing warnings reuse durable, recoverable Discord delivery."""

import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from flow_helpers import closing_event, closing_message, event_body, login
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.announcements import dispatch_due
from app.discord_api import DiscordRequestError
from app.models import Announcement, Event
from app.signup_warnings import DEFAULT_WARNING_MESSAGE, enqueue_due


def due_event(client, message=""):
    headers, event, path, _ = closing_event(client)
    with Session(client.app.state.engine) as db:
        saved = db.get(Event, event["id"])
        saved.post_warning_message = True
        saved.warning_hours_before_close = 1
        saved.warning_message = message
        saved.closes_at = time.time() + 1800
        db.commit()
    return headers, event, path


def dispatch(client):
    dispatch_due(
        client.app.state.engine, lambda guild, channel: client.app.state.discord
    )


def test_default_warning_is_sent_once_with_link_and_closing_time(client):
    _, event, _ = due_event(client)
    engine = client.app.state.engine
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: enqueue_due(engine), range(2)))
    dispatch(client)
    enqueue_due(engine)
    dispatch(client)
    discord = client.app.state.discord
    discord.send_announcement.assert_called_once()
    channel, payload = discord.send_announcement.call_args.args
    assert channel == "thread"
    assert DEFAULT_WARNING_MESSAGE in payload["content"]
    assert "discord.com/channels/guild/channel/message" in payload["content"]
    assert "<t:" in payload["content"]
    assert payload["allowed_mentions"] == {"parse": []}
    with Session(engine) as db:
        rows = list(db.scalars(select(Announcement)))
        assert len(rows) == 1
        assert rows[0].kind == "warning" and rows[0].state == "sent"
        assert rows[0].event_id == event["id"]


@pytest.mark.parametrize(
    "condition", ["disabled", "too_early", "expired", "closed", "archived"]
)
def test_warnings_are_not_enqueued_outside_the_open_warning_window(client, condition):
    _, event, _ = due_event(client)
    with Session(client.app.state.engine) as db:
        saved = db.get(Event, event["id"])
        if condition == "disabled":
            saved.post_warning_message = False
        elif condition == "too_early":
            saved.closes_at = time.time() + 7200
        elif condition == "expired":
            saved.closes_at = time.time() - 1
        elif condition == "closed":
            saved.status = "review"
        else:
            saved.archived_at = time.time()
        db.commit()
    enqueue_due(client.app.state.engine)
    dispatch(client)
    client.app.state.discord.send_announcement.assert_not_called()


def test_custom_warning_retries_rate_limits_without_creating_another_job(client):
    _, _, _ = due_event(client, "Last call for tonight's games!")
    discord = client.app.state.discord
    enqueue_due(client.app.state.engine)
    discord.send_announcement.side_effect = DiscordRequestError(429, 1)
    dispatch(client)
    discord.send_announcement.side_effect = None
    with Session(client.app.state.engine) as db:
        row = db.scalar(select(Announcement))
        row.next_attempt = 0
        db.commit()
    enqueue_due(client.app.state.engine)
    dispatch(client)
    assert discord.send_announcement.call_count == 2
    assert (
        "Last call for tonight's games!"
        in discord.send_announcement.call_args.args[1]["content"]
    )
    with Session(client.app.state.engine) as db:
        assert db.query(Announcement).count() == 1
        assert db.scalar(select(Announcement)).state == "sent"


def test_unknown_delivery_is_reconciled_without_blindly_posting_again(client):
    due_event(client)
    discord = client.app.state.discord
    enqueue_due(client.app.state.engine)
    discord.send_announcement.side_effect = DiscordRequestError(None)
    dispatch(client)
    with Session(client.app.state.engine) as db:
        db.scalar(select(Announcement)).next_attempt = 0
        db.commit()
    discord.send_announcement.side_effect = None
    discord.find_announcement.return_value = "accepted-warning"
    dispatch(client)
    assert discord.send_announcement.call_count == 1
    discord.find_announcement.assert_called_once()


def test_queued_warning_is_suppressed_after_close_and_does_not_block_assignments(
    client,
):
    headers, _, path = due_event(client)
    enqueue_due(client.app.state.engine)
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    dispatch(client)
    assert all(
        DEFAULT_WARNING_MESSAGE not in call.args[1].get("content", "")
        for call in client.app.state.discord.send_announcement.call_args_list
    )
    assert client.get(path + "/announcement").json()["status"] == "sent"


@pytest.mark.parametrize("delete_messages", [False, True])
def test_open_event_with_a_posted_warning_can_be_deleted(client, delete_messages):
    headers, _, path = due_event(client)
    enqueue_due(client.app.state.engine)
    dispatch(client)
    suffix = "?delete_poll=true" if delete_messages else ""
    assert client.delete(path + suffix, headers=headers).status_code == 204
    with Session(client.app.state.engine) as db:
        assert db.query(Announcement).count() == 0
    warning_delete = client.app.state.discord.at.return_value.delete_poll
    if delete_messages:
        warning_delete.assert_called_once_with("announcement")
    else:
        warning_delete.assert_not_called()


def test_warning_settings_survive_event_template_editing_and_require_a_deadline(client):
    headers = login(client)
    settings = {
        "post_warning_message": True,
        "warning_hours_before_close": 2,
        "warning_message": " Last call! ",
    }
    body = {**event_body(), **settings}
    created = client.post("/api/events", headers=headers, json=body)
    assert created.status_code == 201
    assert created.json()["warning_message"] == "Last call!"
    assert created.json()["warning_hours_before_close"] == 2
    path = f"/api/events/{created.json()['id']}"
    updated = client.put(
        path, headers=headers, json={**body, "warning_hours_before_close": 3}
    )
    assert updated.json()["warning_hours_before_close"] == 3
    template = {k: v for k, v in body.items() if k != "starts_at"}
    assert client.post("/api/templates", headers=headers, json=template).json()[
        "post_warning_message"
    ]
    assert client.get("/api/templates").json()[0]["warning_message"] == "Last call!"
    invalid = client.post(
        "/api/events", headers=headers, json={**body, "duration_hours": 0}
    )
    assert invalid.status_code == 422
    assert "closing time" in invalid.json()["detail"][0]["msg"]


def test_recurring_occurrences_inherit_warning_configuration(client):
    headers = login(client)
    settings = {
        "post_warning_message": True,
        "warning_hours_before_close": 2,
        "warning_message": "Last call!",
    }
    response = client.post(
        "/api/recurring-series",
        headers=headers,
        json={
            **event_body(),
            **settings,
            "frequency": "weekly",
            "time_zone": "UTC",
            "opens_before_hours": 72,
            "closes_before_hours": 24,
        },
    )
    assert response.status_code == 201
    occurrences = [
        row
        for row in client.get("/api/events").json()
        if row["series_id"] == response.json()["id"]
    ]
    assert len(occurrences) == 4
    assert all(
        all(row[key] == value for key, value in settings.items()) for row in occurrences
    )


def test_warning_is_rechecked_if_thread_creation_runs_past_the_deadline(client):
    _, event, _ = due_event(client)

    def create_thread(*args):
        with Session(client.app.state.engine) as db:
            db.get(Event, event["id"]).closes_at = time.time() - 1
            db.commit()
        return "thread"

    client.app.state.discord.event_thread.side_effect = create_thread
    enqueue_due(client.app.state.engine)
    dispatch(client)
    client.app.state.discord.send_announcement.assert_not_called()


def test_warning_cleanup_finishes_when_its_thread_has_already_been_deleted(client):
    headers, _, path = due_event(client)
    enqueue_due(client.app.state.engine)
    with Session(client.app.state.engine) as db:
        row = db.scalar(select(Announcement))
        row.unknown = True
        row.state = "needs_review"
        row.channel_id = "deleted-thread"
        db.commit()
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    dispatch(client)
    client.app.state.discord.at.return_value.find_announcement.side_effect = (
        DiscordRequestError(404)
    )
    response = client.post(
        path + "/archive?delete_discord_messages=true", headers=headers
    )
    assert response.status_code == 200
    assert response.json()["discord_cleanup_remaining"] == 0


def test_backed_off_warning_does_not_block_automatic_assignment_delivery(client):
    from app.closing import close_and_assign

    _, event, path = due_event(client)
    enqueue_due(client.app.state.engine)
    with Session(client.app.state.engine) as db:
        db.scalar(select(Announcement)).next_attempt = time.time() + 3600
        db.get(Event, event["id"]).closes_at = time.time() - 1
        db.commit()
    client.app.state.discord.poll_message.return_value = closing_message()
    assert close_and_assign(
        client.app.state.engine,
        client.app.state.discord,
        event["id"],
        "system:auto",
        "channel",
    )
    dispatch(client)
    assert client.get(path + "/announcement").json()["status"] == "sent"
    assert client.app.state.discord.send_announcement.call_count == 2
    assert all(
        DEFAULT_WARNING_MESSAGE not in call.args[1].get("content", "")
        for call in client.app.state.discord.send_announcement.call_args_list
    )
