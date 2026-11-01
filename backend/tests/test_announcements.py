from unittest.mock import Mock

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.announcements import deliver_event, enqueue, payloads
from app.models import Announcement, Base, Event


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
    text = "\n".join(p["content"] for p in chunks)
    assert "Private Real Name" not in text
    assert "weight" not in text
    for player in players:
        assert text.count(f"<@{player['id']}>") == 1
    assert chunks == payloads(event, "channel", result, snapshot)


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
        row = db.query(Announcement).one()
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
        assert db.query(Announcement).one().message_id == "existing"
        assert db.query(Announcement).one().state == "sent"
    engine.dispose()


def test_multipart_retry_keeps_already_sent_parts(tmp_path):
    from app.discord_api import DiscordRequestError

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
