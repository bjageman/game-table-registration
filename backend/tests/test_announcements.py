from unittest.mock import Mock

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.discord.announcements import deliver_event, enqueue, payloads
from app.discord.discord_format import TABLE_FIELD_SPACER
from app.events.event_description import REACTION_DESCRIPTION, signup_embed
from app.models import Announcement, Base, Event


def test_small_assignment_fits_tables_and_waitlist_in_one_message():
    event = Event(id="event", guild_id="guild", title="Active Check", message_id="poll")
    one = {"id": "1", "name": "One", "choices": ["First"], "weight": 1.0}
    two = {"id": "2", "name": "Two", "choices": ["Second"], "weight": 1.0}
    waiting = {"id": "3", "name": "Waiting", "choices": ["First"], "weight": 1.0}
    result = {
        "tables": [
            {"name": "First", "players": [one]},
            {"name": "Second", "players": [two]},
        ],
        "waitlist": ["3"],
    }
    messages = payloads(
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
        ("Waitlist (1)", False),
    ]
    assert fields[2]["value"] == "1. <@3>"
    assert all(field["value"].endswith(TABLE_FIELD_SPACER) for field in fields[:2])


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
    assignment = payloads(
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
        "tables": [{"name": "A", "players": players[:300]}],
        "waitlist": [p["id"] for p in players[300:]],
    }
    chunks = payloads(event, "channel", result, snapshot)
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
    assert chunks == payloads(event, "channel", result, snapshot)
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
        enqueue(
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
        enqueue(
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
        enqueue(
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
    messages = payloads(
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
