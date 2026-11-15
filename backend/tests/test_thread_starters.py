"""Neutral thread starters avoid displaying signup controls inside event threads."""

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_event_threads import setup as setup

from app.discord.discord_api import DiscordRequestError
from app.discord.event_threads import synchronize_event, update_channel
from app.models import Announcement, Event


def test_neutral_starter_is_reused_and_precedes_warning(setup):
    engine, discord = setup
    with Session(engine) as db:
        db.add(
            Announcement(
                id="warning",
                event_id="event",
                part=-1,
                kind="warning",
                channel_id="100",
                payload={"content": "Warning"},
                created_at=0,
                next_attempt=0,
            )
        )
        db.commit()
    synchronize_event(engine, discord, "event")
    synchronize_event(engine, discord, "event")
    discord.event_thread.assert_called_once_with("100", "300", "Monday Games")
    discord.send_announcement.assert_called_once()
    channel, payload = discord.send_announcement.call_args.args
    assert channel == "100"
    assert payload["content"] == "**Monday Games** — Event updates"
    assert "components" not in payload and "embeds" not in payload
    assert payload["allowed_mentions"] == {"parse": []}
    with Session(engine) as db:
        starter = db.scalar(
            select(Announcement).where(Announcement.kind == "thread_starter")
        )
        assert starter.state == "sent" and starter.message_id == "300"
        assert starter.part == -2


def test_uncertain_starter_delivery_is_reconciled_without_duplicate_post(setup):
    engine, discord = setup
    discord.send_announcement.side_effect = DiscordRequestError(None)
    with pytest.raises(HTTPException):
        update_channel(engine, discord, "event")
    discord.event_thread.assert_not_called()
    with Session(engine) as db:
        starter = db.scalar(select(Announcement))
        assert starter.unknown
        starter.next_attempt = 0
        db.commit()
    discord.find_announcement.return_value = "recovered-starter"
    assert update_channel(engine, discord, "event") == "200"
    discord.send_announcement.assert_called_once()
    discord.find_announcement.assert_called_once()
    discord.event_thread.assert_called_once_with(
        "100", "recovered-starter", "Monday Games"
    )


def test_existing_threads_are_kept_without_creating_a_starter(setup):
    engine, discord = setup
    with Session(engine) as db:
        db.get(Event, "event").update_thread_id = "existing-thread"
        db.commit()
    assert update_channel(engine, discord, "event") == "existing-thread"
    discord.event_thread.assert_not_called()
    discord.send_announcement.assert_not_called()


def test_deleting_open_event_also_deletes_its_neutral_starter(client):
    from flow_helpers import closing_event

    headers, event, path, _ = closing_event(client)
    update_channel(client.app.state.engine, client.app.state.discord, event["id"])
    assert client.delete(path + "?delete_poll=true", headers=headers).status_code == 204
    client.app.state.discord.at.return_value.delete_poll.assert_called_with(
        "announcement"
    )
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(Announcement)) is None
