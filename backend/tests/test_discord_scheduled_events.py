"""Server event delivery preserves signups and handles uncertain creation safely."""

import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flow_helpers import event_body, login
from sqlalchemy.orm import Session

from app.discord.discord_api import DiscordAPI, DiscordRequestError
from app.discord.scheduled_events import synchronize_event
from app.models import Announcement, DiscordScheduledEvent, Event


def client_mock():
    discord = Mock(spec=DiscordAPI)
    discord.settings = SimpleNamespace(discord_channel_id="channel")
    discord.create_scheduled_event.return_value = {"id": "server-event"}
    return discord


def queued(engine):
    with Session(engine) as db:
        event = db.get(Event, "event")
        event.status = "open"
        event.description = "Bring a game"
        event.location = "Game Store"
        event.ends_at = event.starts_at + 4 * 3600
        db.add(DiscordScheduledEvent(event_id=event.id))
        db.commit()


def due(engine):
    with Session(engine) as db:
        db.get(DiscordScheduledEvent, "event").checked_at = time.time() - 61
        db.commit()


def test_create_once_then_link_to_delivered_roster(promotion_db):
    queued(promotion_db)
    discord = client_mock()
    synchronize_event(promotion_db, discord, "event")
    body = discord.create_scheduled_event.call_args.args[0]
    assert body["name"] == "Game Night"
    assert body["entity_metadata"] == {"location": "Game Store"}
    assert (
        body["description"]
        == "Game Store\n\nBring a game\n\nhttps://discord.com/channels/guild/channel/signup"
    )
    assert body["scheduled_end_time"] > body["scheduled_start_time"]
    due(promotion_db)
    synchronize_event(promotion_db, discord, "event")
    discord.create_scheduled_event.assert_called_once()
    discord.update_scheduled_event.assert_not_called()
    with Session(promotion_db) as db:
        db.get(Event, "event").status = "review"
        db.commit()
    due(promotion_db)
    synchronize_event(promotion_db, discord, "event")
    discord.update_scheduled_event.assert_not_called()
    with Session(promotion_db) as db:
        db.get(Event, "event").status = "assigned"
        announcement = db.get(Announcement, "assignment")
        announcement.state = "sent"
        announcement.message_id = "roster"
        db.commit()
    due(promotion_db)
    synchronize_event(promotion_db, discord, "event")
    assert discord.update_scheduled_event.call_args.args[0] == "server-event"
    assert discord.update_scheduled_event.call_args.args[1]["description"].endswith(
        "/channel/roster"
    )
    discord.create_scheduled_event.assert_called_once()


def test_uncertain_creation_is_reconciled_without_another_post(promotion_db):
    queued(promotion_db)
    discord = client_mock()
    discord.create_scheduled_event.side_effect = DiscordRequestError(None)
    synchronize_event(promotion_db, discord, "event")
    due(promotion_db)
    discord.scheduled_events.return_value = []
    synchronize_event(promotion_db, discord, "event")
    discord.create_scheduled_event.assert_called_once()
    due(promotion_db)
    discord.scheduled_events.return_value = [
        {
            "id": "found",
            "description": "https://discord.com/channels/guild/channel/signup",
        }
    ]
    synchronize_event(promotion_db, discord, "event")
    with Session(promotion_db) as db:
        record = db.get(DiscordScheduledEvent, "event")
        assert record.discord_id == "found"
        assert record.error is None


def test_permissions_failure_retries_without_affecting_signups(promotion_db):
    queued(promotion_db)
    discord = client_mock()
    discord.create_scheduled_event.side_effect = DiscordRequestError(403)
    synchronize_event(promotion_db, discord, "event")
    with Session(promotion_db) as db:
        assert db.get(Event, "event").status == "open"
        record = db.get(DiscordScheduledEvent, "event")
        assert record.state == "pending"
        assert "Create Events" in record.error
    due(promotion_db)
    discord.create_scheduled_event.side_effect = None
    synchronize_event(promotion_db, discord, "event")
    assert discord.create_scheduled_event.call_count == 2


@pytest.mark.parametrize("enabled", [True, False])
def test_publication_respects_scoped_setting(client, enabled):
    headers = login(client)
    settings = client.get("/api/settings/assignment").json()
    settings["create_discord_event"] = enabled
    assert (
        client.put(
            "/api/settings/assignment", headers=headers, json=settings
        ).status_code
        == 200
    )
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    assert (
        client.post(f"/api/events/{event['id']}/publish", headers=headers).status_code
        == 200
    )
    with Session(client.app.state.engine) as db:
        assert bool(db.get(DiscordScheduledEvent, event["id"])) == enabled
        saved = db.get(Event, event["id"])
        assert saved.ends_at == (saved.starts_at + 4 * 3600 if enabled else None)


def test_end_time_validation_and_round_trip(client):
    from datetime import datetime, timedelta

    headers = login(client)
    body = event_body()
    start = datetime.fromisoformat(body["starts_at"])
    body["ends_at"] = (start - timedelta(hours=1)).isoformat()
    assert client.post("/api/events", headers=headers, json=body).status_code == 422
    body["ends_at"] = (start + timedelta(hours=4)).isoformat()
    response = client.post("/api/events", headers=headers, json=body)
    assert response.status_code == 201
    assert response.json()["ends_at"] - response.json()["starts_at"] == 4 * 3600


def test_recurring_occurrences_keep_the_event_duration(client):
    from datetime import datetime, timedelta

    headers = login(client)
    body = event_body()
    start = datetime.fromisoformat(body["starts_at"])
    body.update(
        ends_at=(start + timedelta(hours=6)).isoformat(),
        frequency="weekly",
        time_zone="UTC",
        opens_before_hours=72,
        closes_before_hours=24,
    )
    response = client.post("/api/recurring-series", headers=headers, json=body)
    assert response.status_code == 201
    series = client.get("/api/recurring-series").json()[0]
    assert series["ends_at"] - series["starts_at"] == 6 * 3600
    events = client.get("/api/events").json()
    assert len(events) == 4
    assert all(event["ends_at"] - event["starts_at"] == 6 * 3600 for event in events)


@pytest.mark.parametrize("action", ["archive", "delete"])
@pytest.mark.parametrize("delete_discord", [True, False])
def test_cleanup_option_only_deletes_linked_server_event(
    client, action, delete_discord
):
    from flow_helpers import closing_event, closing_message

    headers, event, path, _ = closing_event(client)
    if action == "archive":
        client.app.state.discord.poll_message.return_value = closing_message()
        assert client.post(path + "/close", headers=headers).status_code == 200
    with Session(client.app.state.engine) as db:
        record = db.get(DiscordScheduledEvent, event["id"])
        record.discord_id = "server-event"
        record.state = "synced"
        db.commit()
    client.app.state.discord.reset_mock()
    query = {"delete_discord_event": delete_discord}
    response = (
        client.post(path + "/archive", headers=headers, params=query)
        if action == "archive"
        else client.delete(path, headers=headers, params=query)
    )
    assert response.status_code == (200 if action == "archive" else 204)
    deleted = any(
        call.args == ("DELETE", "/guilds/guild/scheduled-events/server-event")
        for call in client.app.state.discord.mock_calls
    )
    assert deleted == delete_discord
    if action == "archive":
        assert response.json()["has_discord_event"] != delete_discord


def test_deleted_pending_server_event_is_not_created_later(promotion_db):
    from app.discord.scheduled_events import delete_scheduled_event

    queued(promotion_db)
    discord = client_mock()
    with Session(promotion_db) as db:
        delete_scheduled_event(db, db.get(Event, "event"), discord)
        db.commit()
    synchronize_event(promotion_db, discord, "event")
    discord.create_scheduled_event.assert_not_called()
