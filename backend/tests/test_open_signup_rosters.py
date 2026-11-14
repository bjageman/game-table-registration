import time
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.discord.discord_api import DiscordRequestError
from app.discord.open_signup_rosters import base_embed, roster_pages, synchronize_due
from app.discord.reactions import change
from app.models import (
    AssignmentPreference,
    Base,
    Event,
    EventManagerSignup,
    TableSignup,
)


@pytest.fixture
def roster(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/roster.db")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(
            Event(
                id="event",
                title="Game Night",
                description="Bring friends",
                location="Club",
                guild_id="guild",
                channel_id="channel",
                message_id="signup",
                created_by="owner",
                status="open",
                signup_mode="reactions",
                starts_at=time.time() + 7200,
                closes_at=time.time() + 3600,
                duration_hours=1,
                reaction_checkpoint=time.time(),
                published_at=time.time(),
                tables=[{"name": "A", "capacity": 2}, {"name": "B", "capacity": 2}],
            )
        )
        db.add(
            AssignmentPreference(scope_key="user:owner", show_open_signup_players=True)
        )
        db.add_all(
            [
                TableSignup(
                    event_id="event",
                    discord_id="1",
                    discord_name="One",
                    choices=["A", "B"],
                ),
                TableSignup(
                    event_id="event", discord_id="2", discord_name="Two", choices=["A"]
                ),
            ]
        )
        db.commit()
    discord = Mock()
    discord.find_announcement.return_value = None
    counter = iter(range(1, 1000))
    discord.send_announcement.side_effect = lambda *_: {
        "id": f"continuation-{next(counter)}"
    }
    factory = Mock(return_value=discord)
    yield engine, discord, factory
    engine.dispose()


def due_again(engine):
    with Session(engine) as db:
        db.get(Event, "event").signup_roster_checked_at = None
        db.commit()


def last_embed(discord):
    return discord.edit_announcement.call_args.args[2]["embeds"][0]


def test_counts_unique_people_and_only_edits_changed_rosters(roster):
    engine, discord, factory = roster
    synchronize_due(engine, factory)
    embed = last_embed(discord)
    assert embed["title"] == "Game Night"
    assert embed["description"].startswith("Bring friends\n\nEvent:")
    assert "Total users signed up: 2" in embed["description"]
    assert [field["name"] for field in embed["fields"]] == ["1️⃣ A (2/2)", "2️⃣ B (1/2)"]
    assert (
        "<@1>" in embed["fields"][0]["value"] and "<@1>" in embed["fields"][1]["value"]
    )
    assert all(field["inline"] is True for field in embed["fields"])
    assert discord.edit_announcement.call_args.args[2]["allowed_mentions"] == {
        "parse": [],
        "users": [],
    }
    synchronize_due(engine, factory)
    assert discord.edit_announcement.call_count == 1
    due_again(engine)
    synchronize_due(engine, factory)
    assert discord.edit_announcement.call_count == 1
    change(engine, "event", "2️⃣", "3", "Three", True, time.time())
    due_again(engine)
    synchronize_due(engine, factory)
    assert "Total users signed up: 3" in last_embed(discord)["description"]
    assert "<@3>" in last_embed(discord)["fields"][1]["value"]


def test_default_off_skips_network_and_disabling_restores_original_format(roster):
    engine, discord, factory = roster
    with Session(engine) as db:
        db.get(AssignmentPreference, "user:owner").show_open_signup_players = False
        db.commit()
    synchronize_due(engine, factory)
    factory.assert_not_called()
    with Session(engine) as db:
        db.get(AssignmentPreference, "user:owner").show_open_signup_players = True
        db.commit()
    synchronize_due(engine, factory)
    with Session(engine) as db:
        db.get(AssignmentPreference, "user:owner").show_open_signup_players = False
        db.commit()
    due_again(engine)
    synchronize_due(engine, factory)
    restored = discord.edit_announcement.call_args.args[2]
    assert restored["embeds"] == []
    assert "**Game Night**" in restored["content"]
    assert "1️⃣ A · 2 seats" in restored["content"]
    assert "Total users signed up" not in restored["content"]
    with Session(engine) as db:
        assert db.get(Event, "event").signup_roster_hash is None
    discord.reset_mock()
    due_again(engine)
    synchronize_due(engine, factory)
    discord.edit_announcement.assert_not_called()


def test_manager_overrides_test_players_and_reaction_removals_are_reflected(roster):
    engine, discord, factory = roster
    with Session(engine) as db:
        db.add(
            EventManagerSignup(
                event_id="event",
                discord_id="1",
                discord_name="One",
                choices=[],
                removed=True,
            )
        )
        db.add(
            EventManagerSignup(
                event_id="event",
                discord_id="4",
                discord_name="Four",
                choices=["A", "B"],
                removed=False,
            )
        )
        db.get(Event, "event").test_signups = {
            "players": [{"id": "test-player", "name": "Test name", "choices": ["B"]}]
        }
        db.commit()
    change(engine, "event", "1️⃣", "2", "Two", False, time.time())
    synchronize_due(engine, factory)
    embed = last_embed(discord)
    assert "Total users signed up: 2" in embed["description"]
    text = "\n".join(field["value"] for field in embed["fields"])
    assert "<@1>" not in text and "<@2>" not in text
    assert text.count("<@4>") == 2
    assert "Test name" in text and "<@test-" not in text


def test_retries_failed_edits_and_ignores_unhealthy_or_closed_events(roster):
    engine, discord, factory = roster
    discord.edit_announcement.side_effect = DiscordRequestError(429)
    synchronize_due(engine, factory)
    assert discord.edit_announcement.call_count == 1
    synchronize_due(engine, factory)
    assert discord.edit_announcement.call_count == 1
    discord.edit_announcement.side_effect = None
    due_again(engine)
    synchronize_due(engine, factory)
    assert discord.edit_announcement.call_count == 2
    for change_values in [
        {"reaction_error": "Needs sync"},
        {"status": "assigned", "reaction_error": None},
    ]:
        with Session(engine) as db:
            event = db.get(Event, "event")
            for key, value in change_values.items():
                setattr(event, key, value)
            db.commit()
        due_again(engine)
        synchronize_due(engine, factory)
        assert discord.edit_announcement.call_count == 2


def test_poll_rosters_reconcile_live_voters_and_do_not_edit_after_concurrent_close(
    roster,
):
    engine, discord, factory = roster
    with Session(engine) as db:
        db.get(Event, "event").signup_mode = "poll"
        db.commit()
    discord.table_signups.return_value = [
        {"name": "A", "players": [{"id": "7", "name": "Seven"}]},
        {"name": "B", "players": [{"id": "7", "name": "Seven"}]},
    ]
    synchronize_due(engine, factory)
    assert "Total users signed up: 1" in last_embed(discord)["description"]
    assert all("<@7>" in field["value"] for field in last_embed(discord)["fields"])

    def close_during_fetch(*_):
        with Session(engine) as db:
            db.get(Event, "event").status = "assigned"
            db.commit()
        return []

    discord.table_signups.side_effect = close_during_fetch
    due_again(engine)
    synchronize_due(engine, factory)
    assert discord.edit_announcement.call_count == 1


def test_large_rosters_are_complete_paginated_and_cleaned_up_on_disable(roster):
    engine, discord, factory = roster
    people = [
        {"id": str(100000000000000000 + index), "name": f"Player {index}"}
        for index in range(1000)
    ]
    rows = [{"name": name, "players": people} for name in ["A", "B"]]
    with Session(engine) as db:
        event = db.get(Event, "event")
        event.signup_mode = "poll"
        pages = roster_pages(event, base_embed(event), rows)
        db.commit()
    assert len(pages) > 1
    assert "Total users signed up: 1000" in pages[0]["description"]
    for page in pages:
        assert len(page["fields"]) <= 25
        assert (
            len(page["title"])
            + len(page["description"])
            + sum(len(field["name"]) + len(field["value"]) for field in page["fields"])
            <= 6000
        )
        assert all(len(field["value"]) <= 1024 for field in page["fields"])
    text = "\n".join(field["value"] for page in pages for field in page["fields"])
    assert all(text.count(f"<@{person['id']}>") == 2 for person in people)
    discord.table_signups.return_value = rows
    for _ in range(5):
        synchronize_due(engine, factory)
        due_again(engine)
    with Session(engine) as db:
        saved = db.get(Event, "event")
        assert saved.signup_roster_hash != "pending"
        assert len(saved.signup_roster_messages) == len(pages)
        db.get(AssignmentPreference, "user:owner").show_open_signup_players = False
        db.commit()
    for _ in range(5):
        synchronize_due(engine, factory)
        due_again(engine)
    with Session(engine) as db:
        assert db.get(Event, "event").signup_roster_hash is None
        assert db.get(Event, "event").signup_roster_messages is None
    assert discord.bot.call_count == len(pages) - 1


def test_organization_option_is_independent_from_personal_preferences(roster):
    from app.models import Organization

    engine, discord, factory = roster
    with Session(engine) as db:
        db.add(
            Organization(
                id="org",
                name="Org",
                normalized_name="org",
                created_by="owner",
                guild_id="guild",
                channel_id="channel",
            )
        )
        db.flush()
        db.get(Event, "event").organization_id = "org"
        db.add(
            AssignmentPreference(scope_key="org:org", show_open_signup_players=False)
        )
        db.commit()
    synchronize_due(engine, factory)
    factory.assert_not_called()
    with Session(engine) as db:
        db.get(AssignmentPreference, "org:org").show_open_signup_players = True
        db.get(AssignmentPreference, "user:owner").show_open_signup_players = False
        db.commit()
    synchronize_due(engine, factory)
    discord.edit_announcement.assert_called_once()


def test_uncertain_continuation_send_is_reconciled_before_reposting(roster):
    engine, discord, factory = roster
    people = [
        {"id": str(100000000000000000 + index), "name": "Player"}
        for index in range(1000)
    ]
    with Session(engine) as db:
        db.get(Event, "event").signup_mode = "poll"
        db.commit()
    discord.table_signups.return_value = [
        {"name": name, "players": people} for name in ["A", "B"]
    ]
    uncertain = []

    def send(_channel, payload):
        if not uncertain:
            uncertain.append(payload["content"])
            raise DiscordRequestError(None)
        return {"id": f"sent-{discord.send_announcement.call_count}"}

    discord.send_announcement.side_effect = send
    discord.find_announcement.side_effect = lambda channel, payload, attempted: (
        "recovered" if payload["content"] in uncertain else None
    )
    synchronize_due(engine, factory)
    assert discord.send_announcement.call_count == 1
    due_again(engine)
    synchronize_due(engine, factory)
    with Session(engine) as db:
        saved = db.get(Event, "event")
        assert saved.signup_roster_messages[1]["id"] == "recovered"
        assert saved.signup_roster_hash != "pending"
    assert (
        sum(
            call.args[1]["content"] == uncertain[0]
            for call in discord.send_announcement.call_args_list
        )
        == 1
    )


def test_roster_sync_defaults_on_without_saved_preferences(roster):
    from sqlalchemy import delete

    engine, discord, factory = roster
    with Session(engine) as db:
        db.execute(delete(AssignmentPreference))
        db.commit()
    synchronize_due(engine, factory)
    factory.assert_called_once_with("guild", "channel")
    assert "<@1>" in str(last_embed(discord))
