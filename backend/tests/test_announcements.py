from unittest.mock import Mock

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.discord.announcements import deliver_event
from app.discord.discord_format import TABLE_FIELD_SPACER
from app.discord.event_messages import (
    REACTION_DESCRIPTION,
    build_assignment_messages,
    enqueue_assignment_messages,
    signup_embed,
)
from app.models import Announcement, Base, Event


def test_small_assignment_fits_tables_and_waitlist_in_one_message():
    event = Event(id="event", guild_id="guild", title="Active Check", message_id="poll")
    one = {"id": "1", "name": "One", "choices": ["First"], "weight": 1.0}
    two = {"id": "2", "name": "Two", "choices": ["Second"], "weight": 1.0}
    waiting = {"id": "3", "name": "Waiting", "choices": ["First"], "weight": 1.0}
    result = {
        "tables": [
            {"name": "First", "players": [one], "waitlist": [waiting]},
            {"name": "Second", "players": [two], "waitlist": [waiting]},
        ],
        "waitlist": ["3"],
    }
    messages = build_assignment_messages(
        event, "channel", result, {"players": [one, two, waiting], "is_test": True}
    )
    assert len(messages) == 1
    embed = messages[0]["embeds"][0]
    assert embed["title"] == "[TEST] Active Check"
    assert "Table assignments are ready." in embed["description"]
    assert "[Signup message]" in embed["description"]
    fields = embed["fields"]
    assert [(field["name"], field["inline"]) for field in fields] == [
        ("First (1)", True),
        ("Second (1)", True),
    ]
    assert fields[0]["value"] == f"<@1>\n\n⌛ Waitlist\n1. <@3>{TABLE_FIELD_SPACER}"
    assert fields[1]["value"] == f"<@2>\n\n⌛ Waitlist\n1. <@3>{TABLE_FIELD_SPACER}"
    assert all(field["value"].endswith(TABLE_FIELD_SPACER) for field in fields[:2])


def test_table_waitlist_preserves_order_without_notifying_waiting_players():
    event = Event(id="event", guild_id="guild", title="Games", message_id="poll")
    seated = {"id": "1", "name": "Seated"}
    first = {"id": "3", "name": "First waiting"}
    second = {"id": "2", "name": "Second waiting"}
    message = build_assignment_messages(
        event,
        "channel",
        {
            "tables": [
                {"name": "A", "players": [seated]},
                {"name": "B", "players": [], "waitlist": [first, second]},
            ],
            "waitlist": ["2", "3"],
        },
        {"players": [seated]},
    )[0]
    fields = message["embeds"][0]["fields"]
    assert fields[0]["value"] == f"<@1>{TABLE_FIELD_SPACER}"
    assert fields[1]["value"] == (
        "No players assigned.\n\n⌛ Waitlist\n1. <@3>\n2. <@2>" + TABLE_FIELD_SPACER
    )
    assert message["content"] == "<@1>"
    assert message["allowed_mentions"] == {"parse": [], "users": ["1"]}


def test_assignment_embed_shares_signup_title_and_event_layout():
    event = Event(
        id="event",
        guild_id="guild",
        title="Game Night",
        description="Bring friends",
        location="Club",
        starts_at=2_000_000_000,
        message_id="signup",
        tables=[{"name": "A", "capacity": 4}],
    )
    assignment = build_assignment_messages(
        event,
        "channel",
        {"tables": [{"name": "A", "players": []}], "waitlist": []},
        {"players": []},
    )[0]["embeds"][0]
    signup = signup_embed(event, REACTION_DESCRIPTION, "Signups close soon", ["1️⃣ A"])
    assert assignment["title"] == signup["title"]
    assert assignment["color"] == signup["color"]
    assert assignment["description"].startswith("Bring friends\n\nEvent:")
    assert assignment["description"].index("Event:") < assignment["description"].index(
        "Location:"
    )
    assert assignment["fields"][0]["inline"] is True
    for embed in (assignment, signup):
        assert embed["fields"][0]["value"].endswith(TABLE_FIELD_SPACER)


def test_large_announcements_are_complete_bounded_and_private():
    event = Event(
        id="event", guild_id="guild", title="Games @everyone", message_id="poll"
    )
    players = [
        {
            "id": str(i),
            "name": f"Private Real Name {i}",
            "choices": ["A"],
            "weight": 2.0,
        }
        for i in range(1, 501)
    ]
    snapshot = {"players": players}
    result = {
        "tables": [{"name": "A", "players": players[:300], "waitlist": players[300:]}],
        "waitlist": [p["id"] for p in players[300:]],
    }
    chunks = build_assignment_messages(event, "channel", result, snapshot)
    assert len(chunks) > 1
    assert len({p["nonce"] for p in chunks}) == len(chunks)
    assert all(len(p["content"]) <= 2000 for p in chunks)
    assert all(len(p["allowed_mentions"]["users"]) <= 100 for p in chunks)
    assert all(p["allowed_mentions"]["parse"] == [] for p in chunks)
    assert all(len(p["embeds"][0]["fields"]) <= 25 for p in chunks)
    fields = [field for p in chunks for field in p["embeds"][0]["fields"]]
    assert all(len(field["value"]) <= 1024 for field in fields)
    assert all(
        sum(
            len(field["name"]) + len(field["value"])
            for field in p["embeds"][0]["fields"]
        )
        <= 6000
        for p in chunks
    )
    content = "\n".join(p["content"] for p in chunks)
    roster = "\n".join(field["value"] for field in fields)
    assert "Private Real Name" not in content + roster
    assert "weight" not in content + roster
    for player in players[:300]:
        assert content.count(f"<@{player['id']}>") == 1
        assert roster.count(f"<@{player['id']}>") == 1
    for player in players[300:]:
        assert f"<@{player['id']}>" not in content
        assert roster.count(f"<@{player['id']}>") == 1
    assert chunks == build_assignment_messages(event, "channel", result, snapshot)
    assert all("Signup message" in p["embeds"][0]["description"] for p in chunks)


def test_expired_delivery_claim_reconciles_the_existing_message(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/outbox.db")
    Base.metadata.create_all(engine)
    event = Event(
        id="event",
        guild_id="guild",
        title="Games",
        message_id="poll",
        starts_at=3800000000,
        duration_hours=24,
        tables=[{"name": "A", "capacity": 1}],
        created_by="owner",
    )
    with Session(engine) as db:
        db.add(event)
        db.flush()
        enqueue_assignment_messages(
            db,
            event,
            "channel",
            {"tables": [{"name": "A", "players": []}], "waitlist": []},
            {"players": []},
        )
        db.flush()
        row = db.query(Announcement).filter_by(kind="assignment").one()
        row.state = "sending"
        row.token = "interrupted"
        row.lease_until = 0
        row.attempted_at = 1
        db.commit()
    discord = Mock()
    discord.find_announcement.return_value = "existing"
    deliver_event(engine, discord, "event")
    discord.send_announcement.assert_not_called()
    with Session(engine) as db:
        row = db.query(Announcement).filter_by(kind="assignment").one()
        assert row.message_id == "existing"
        assert row.state == "sent"
    engine.dispose()


def test_multipart_retry_keeps_already_sent_parts(tmp_path):
    from app.discord.discord_api import DiscordRequestError

    engine = create_engine(f"sqlite:///{tmp_path}/parts.db")
    Base.metadata.create_all(engine)
    players = [
        {"id": str(i), "name": f"Player {i}", "choices": ["A"], "weight": 1.0}
        for i in range(1, 251)
    ]
    event = Event(
        id="event",
        guild_id="guild",
        title="Games",
        message_id="poll",
        starts_at=3800000000,
        duration_hours=24,
        tables=[{"name": "A", "capacity": 250}],
        created_by="owner",
    )
    with Session(engine) as db:
        db.add(event)
        db.flush()
        enqueue_assignment_messages(
            db,
            event,
            "channel",
            {"tables": [{"name": "A", "players": players}], "waitlist": []},
            {"players": players},
        )
        db.commit()
    discord = Mock()
    discord.send_announcement.side_effect = [{"id": "first"}, DiscordRequestError(403)]
    deliver_event(engine, discord, "event", limit=5)
    first_nonce = discord.send_announcement.call_args_list[0].args[1]["nonce"]
    with Session(engine) as db:
        sent = db.query(Announcement).filter_by(state="sent").one()
        assert sent.message_id == "first"
        db.query(Announcement).filter_by(state="pending").update({"next_attempt": 0})
        db.commit()
    discord.send_announcement.side_effect = None
    discord.send_announcement.return_value = {"id": "remaining"}
    deliver_event(engine, discord, "event", limit=5)
    nonces = [
        call.args[1]["nonce"] for call in discord.send_announcement.call_args_list
    ]
    assert nonces.count(first_nonce) == 1
    with Session(engine) as db:
        assert all(row.state == "sent" for row in db.query(Announcement))
    engine.dispose()


def test_two_deliverers_cannot_post_the_same_pending_part(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event as Gate

    engine = create_engine(f"sqlite:///{tmp_path}/concurrent.db")
    Base.metadata.create_all(engine)
    event = Event(
        id="event",
        guild_id="guild",
        title="Games",
        message_id="poll",
        starts_at=3800000000,
        duration_hours=24,
        tables=[{"name": "A", "capacity": 1}],
        created_by="owner",
    )
    with Session(engine) as db:
        db.add(event)
        db.flush()
        enqueue_assignment_messages(
            db,
            event,
            "channel",
            {"tables": [{"name": "A", "players": []}], "waitlist": []},
            {"players": []},
        )
        db.commit()
    entered, release = Gate(), Gate()
    discord = Mock()

    def send(channel_id, payload):
        entered.set()
        assert release.wait(5)
        return {"id": "posted"}

    discord.send_announcement.side_effect = send
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(deliver_event, engine, discord, "event")
        try:
            assert entered.wait(5)
            deliver_event(engine, discord, "event")
        finally:
            release.set()
        first.result(timeout=5)
    discord.send_announcement.assert_called_once()
    discord.find_announcement.assert_not_called()
    engine.dispose()


def test_long_event_details_do_not_overflow_assignment_embeds():
    from app.discord.discord_format import embed_length

    tables = []
    all_players = []
    for index in range(10):
        players = [
            {
                "id": f"test-{index}-{number}",
                "name": f"Player {index} {number:02d}" + "x" * 30,
            }
            for number in range(13)
        ]
        all_players.extend(players)
        tables.append({"name": f"Table {index}", "players": players})
    event = Event(
        id="event",
        guild_id="guild",
        title="T" * 100,
        description="D" * 300,
        location="L" * 200,
        starts_at=2_000_000_000,
        message_id="signup",
        tables=[{"name": table["name"], "capacity": 15} for table in tables],
    )
    messages = build_assignment_messages(
        event,
        "channel",
        {"tables": tables, "waitlist": []},
        {"players": all_players, "is_test": True},
    )
    assert len(messages) > 1
    assert all(embed_length(message["embeds"][0]) <= 6000 for message in messages)
    roster = "\n".join(
        field["value"]
        for message in messages
        for field in message["embeds"][0]["fields"]
    )
    for player in all_players:
        assert roster.count(player["name"]) == 1


def test_mixed_assignment_roster_only_notifies_real_discord_users():
    event = Event(id="event", guild_id="guild", title="Games", message_id="poll")
    players = [
        {"id": "123", "name": "Real Player"},
        {"id": "test-" + "a" * 24, "name": "Test Player 003"},
    ]
    message = build_assignment_messages(
        event,
        "channel",
        {
            "tables": [{"name": "A", "players": players}],
            "waitlist": [],
        },
        {"players": players, "is_test": False},
    )[0]
    assert message["allowed_mentions"]["users"] == ["123"]
    assert message["content"] == "<@123>"
    assert "Test Player 003" in message["embeds"][0]["fields"][0]["value"]


def test_retry_repairs_invalid_test_mentions_in_saved_messages(promotion_db):
    with Session(promotion_db) as db:
        row = db.get(Announcement, "assignment")
        row.state = "pending"
        row.message_id = None
        row.payload = {
            "content": "<@test-example> <@123>",
            "allowed_mentions": {"parse": [], "users": ["test-example", "123"]},
        }
        db.commit()
    discord = Mock()
    discord.send_announcement.return_value = {"id": "posted"}
    deliver_event(promotion_db, discord, "event")
    sent = discord.send_announcement.call_args.args[1]
    assert sent["content"] == "<@123>"
    assert sent["allowed_mentions"]["users"] == ["123"]
    with Session(promotion_db) as db:
        row = db.get(Announcement, "assignment")
        assert row.state == "sent"
        assert row.payload == sent


def test_backed_off_thread_starter_does_not_block_assignments(promotion_db):
    import time

    from app.discord.announcements import dispatch_due, status

    with Session(promotion_db) as db:
        original = db.get(Announcement, "assignment")
        original.state = "pending"
        original.message_id = None
        db.add(
            Announcement(
                id="starter",
                event_id="event",
                part=-2,
                kind="thread_starter",
                channel_id="channel",
                payload={"content": "Event updates"},
                state="pending",
                created_at=0,
                next_attempt=time.time() + 3600,
                error="Thread starter failed",
            )
        )
        db.commit()
    discord = Mock()
    discord.send_announcement.return_value = {"id": "results"}
    dispatch_due(promotion_db, lambda *_: discord)
    discord.send_announcement.assert_called_once()
    with Session(promotion_db) as db:
        assert db.get(Announcement, "assignment").state == "sent"
        assert db.get(Announcement, "starter").state == "pending"
    assert status(promotion_db, "event", "guild")["status"] == "sent"


def test_targeted_thread_starter_delivery_preserves_pending_assignment(promotion_db):
    with Session(promotion_db) as db:
        original = db.get(Announcement, "assignment")
        original.state = "pending"
        db.add(
            Announcement(
                id="starter",
                event_id="event",
                part=-2,
                kind="thread_starter",
                channel_id="channel",
                payload={"content": "Event updates"},
                state="pending",
                created_at=0,
                next_attempt=0,
            )
        )
        db.commit()
    discord = Mock()
    discord.send_announcement.return_value = {"id": "starter-message"}
    deliver_event(promotion_db, discord, "event", kind="thread_starter")
    discord.send_announcement.assert_called_once_with(
        "channel", {"content": "Event updates"}
    )
    with Session(promotion_db) as db:
        assert db.get(Announcement, "assignment").state == "pending"
        assert db.get(Announcement, "starter").state == "sent"
