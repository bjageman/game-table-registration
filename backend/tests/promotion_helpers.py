"""Shared setup for private promotion delivery and Gateway tests."""

from unittest.mock import Mock

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assignments import player_changes
from app.models import PromotionDM


def queued(engine):
    assert player_changes.remove_player_from_roster(engine, "guild", "event", "1")
    with Session(engine) as db:
        notice = db.scalar(select(PromotionDM))
        return notice.id


def discord_client():
    client = Mock()
    client.open_dm.return_value = "private-channel"
    client.send_announcement.return_value = {"id": "private-message"}
    client.find_announcement.return_value = None
    return client
