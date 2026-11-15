"""Durable delivery ownership is identical for public and private messages."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.discord.delivery import claim_delivery, complete_delivery
from app.models import Announcement, Base, PromotionDM


@pytest.mark.parametrize("model", [Announcement, PromotionDM])
def test_expired_worker_cannot_complete_a_reclaimed_delivery(tmp_path, model):
    engine = create_engine(f"sqlite:///{tmp_path / 'delivery.db'}")
    Base.metadata.create_all(engine)
    values = dict(
        id="notice", event_id="event", payload={}, created_at=0, next_attempt=0
    )
    if model is Announcement:
        values.update(part=0, channel_id="channel")
    else:
        values.update(discord_id="player", table_name="Table A")
    with Session(engine) as db:
        db.add(model(**values))
        db.commit()
        first = claim_delivery(db, model, "notice", now=100, attempted_at=100)
        db.commit()
        assert first is not None
        assert claim_delivery(db, model, "notice", now=101, attempted_at=101) is None
        second = claim_delivery(db, model, "notice", now=191, attempted_at=191)
        db.commit()
        assert second is not None and second != first
        complete_delivery(db, model, "notice", first, "stale-message")
        db.commit()
        assert db.get(model, "notice").state == "sending"
        assert db.get(model, "notice").message_id is None
        complete_delivery(db, model, "notice", second, "confirmed-message")
        db.commit()
        row = db.get(model, "notice")
        assert row.state == "sent" and row.message_id == "confirmed-message"
        assert row.token is None and row.lease_until is None
        assert row.attempts == 2
    engine.dispose()
