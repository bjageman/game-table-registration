import asyncio
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.announcements import deliver_event
from app.config import Settings
from app.discord_api import DiscordAPI, DiscordRequestError
from app.event_threads import queue_member, synchronize_event
from app.gateway import SignupGateway
from app.models import (
    Announcement,
    AssignmentPreference,
    Base,
    Event,
    EventThreadMember,
    TableSignup,
)
from app.reactions import change


@pytest.fixture
def setup(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/threads.db")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(
            Event(
                id="event",
                title="Monday Games",
                guild_id="guild",
                channel_id="100",
                message_id="200",
                starts_at=time.time() + 86400,
                closes_at=time.time() + 3600,
                duration_hours=1,
                signup_mode="reactions",
                status="open",
                tables=[{"name": "One", "capacity": 1}],
                created_by="owner",
            )
        )
        db.add(
            AssignmentPreference(
                scope_key="user:owner",
                announce_table_changes=True,
                post_discord_updates_to_thread=True,
            )
        )
        db.commit()
    discord = Mock(spec=DiscordAPI)
    discord.event_thread.return_value = "200"
    discord.send_announcement.return_value = {"id": "300"}
    yield engine, discord
    engine.dispose()


def test_reaction_rsvp_creates_one_named_thread_and_adds_member_once(setup):
    engine, discord = setup
    change(engine, "event", "1️⃣", "123", "Dave", True, time.time())
    synchronize_event(engine, discord, "event")
    synchronize_event(engine, discord, "event")
    discord.event_thread.assert_called_once_with("100", "200", "Monday Games")
    discord.add_thread_member.assert_called_once_with("200", "123")
    discord.send_announcement.assert_not_called()
    with Session(engine) as db:
        assert db.get(Event, "event").update_thread_id == "200"
        assert db.get(EventThreadMember, ("event", "123")).added_at is not None


def test_thread_membership_retries_and_ignores_simulated_players(setup):
    engine, discord = setup
    with Session(engine) as db:
        event = db.get(Event, "event")
        queue_member(db, event, "123")
        queue_member(db, event, "test-123")
        db.commit()
    discord.add_thread_member.side_effect = DiscordRequestError(403)
    synchronize_event(engine, discord, "event")
    with Session(engine) as db:
        assert db.get(EventThreadMember, ("event", "123")).added_at is None
        assert db.get(EventThreadMember, ("event", "test-123")) is None
    discord.add_thread_member.side_effect = None
    synchronize_event(engine, discord, "event")
    discord.event_thread.assert_called_once()
    with Session(engine) as db:
        assert db.get(EventThreadMember, ("event", "123")).added_at is not None


def test_poll_votes_are_backfilled_without_repeated_discord_reads(setup):
    engine, discord = setup
    with Session(engine) as db:
        event = db.get(Event, "event")
        event.signup_mode = "poll"
        event.answers = [{"answer_id": 1}]
        db.commit()
    discord.voters.return_value = [{"id": "123", "name": "Dave"}]
    synchronize_event(engine, discord, "event")
    synchronize_event(engine, discord, "event")
    discord.voters.assert_called_once_with("200", 1)
    discord.add_thread_member.assert_called_once_with("200", "123")


def test_gateway_poll_vote_queues_thread_membership(setup):
    engine, _ = setup
    with Session(engine) as db:
        db.get(Event, "event").signup_mode = "poll"
        db.commit()

    async def vote():
        gateway = SignupGateway(engine, Settings(_env_file=None))
        await gateway.on_raw_poll_vote_add(
            SimpleNamespace(
                guild_id="guild", channel_id=100, message_id=200, user_id=123
            )
        )
        await gateway.close()

    asyncio.run(vote())
    with Session(engine) as db:
        assert db.get(EventThreadMember, ("event", "123")) is not None


def add_notice(engine, kind, part):
    with Session(engine) as db:
        db.add(
            Announcement(
                id=f"notice-{part}",
                event_id="event",
                kind=kind,
                part=part,
                channel_id="100",
                payload={"content": kind},
                created_at=0,
                next_attempt=0,
            )
        )
        db.commit()


def test_assignments_stay_in_channel_and_table_change_notices_use_thread(setup):
    engine, discord = setup
    add_notice(engine, "assignment", 0)
    add_notice(engine, "promotion", 1)
    deliver_event(engine, discord, "event", limit=5)
    assert [call.args[0] for call in discord.send_announcement.call_args_list] == [
        "100",
        "200",
    ]
    with Session(engine) as db:
        notices = list(db.scalars(select(Announcement).order_by(Announcement.part)))
        assert [notice.channel_id for notice in notices] == ["100", "200"]
        assert all(notice.state == "sent" for notice in notices)


def test_thread_creation_failure_retries_without_posting_update_in_main_channel(setup):
    engine, discord = setup
    add_notice(engine, "promotion", 0)
    discord.event_thread.side_effect = DiscordRequestError(403)
    deliver_event(engine, discord, "event")
    discord.send_announcement.assert_not_called()
    with Session(engine) as db:
        notice = db.get(Announcement, "notice-0")
        assert notice.state == "pending"
        assert notice.unknown is False
        notice.next_attempt = 0
        db.commit()
    discord.event_thread.side_effect = None
    deliver_event(engine, discord, "event")
    discord.send_announcement.assert_called_once_with("200", {"content": "promotion"})


def test_disabled_setting_leaves_existing_channel_behavior(setup):
    engine, discord = setup
    with Session(engine) as db:
        db.get(
            AssignmentPreference, "user:owner"
        ).post_discord_updates_to_thread = False
        db.add(
            TableSignup(
                event_id="event", discord_id="123", discord_name="Dave", choices=["One"]
            )
        )
        db.commit()
    synchronize_event(engine, discord, "event")
    add_notice(engine, "promotion", 0)
    deliver_event(engine, discord, "event")
    discord.event_thread.assert_not_called()
    discord.add_thread_member.assert_not_called()
    discord.send_announcement.assert_called_once_with("100", {"content": "promotion"})


def test_start_thread_recovers_an_ambiguous_response_without_a_second_thread():
    discord = DiscordAPI(Settings(_env_file=None))
    discord.bot = Mock(
        side_effect=[
            DiscordRequestError(None),
            {"id": "200", "parent_id": "100", "type": 11},
        ]
    )
    assert discord.event_thread("100", "200", "Monday Games") == "200"
    assert [call.args[:2] for call in discord.bot.call_args_list] == [
        ("POST", "/channels/100/messages/200/threads"),
        ("GET", "/channels/200"),
    ]


def test_ambiguous_update_delivery_recovers_in_the_same_thread(setup):
    engine, discord = setup
    add_notice(engine, "promotion", 0)
    discord.send_announcement.side_effect = DiscordRequestError(None)
    deliver_event(engine, discord, "event")
    with Session(engine) as db:
        notice = db.get(Announcement, "notice-0")
        assert notice.channel_id == "200"
        assert notice.unknown is True
        notice.next_attempt = 0
        db.commit()
    discord.find_announcement.return_value = "300"
    deliver_event(engine, discord, "event")
    discord.event_thread.assert_called_once()
    discord.send_announcement.assert_called_once()
    assert discord.find_announcement.call_args.args[0] == "200"
    with Session(engine) as db:
        assert db.get(Announcement, "notice-0").state == "sent"
