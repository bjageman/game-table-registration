"""Claim editable assignment state within the caller's transaction."""

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Announcement, Event, LotteryRun


def locked_assignment(
    db: Session, guild_id: str, event_id: str
) -> tuple[Event, LotteryRun] | None:
    """Keep this transaction open through the edits and notification outbox writes."""
    claimed = db.execute(
        update(Event)
        .where(
            Event.id == event_id,
            Event.guild_id == guild_id,
            Event.status.in_(["assigned", "review"]),
            Event.archived_at.is_(None),
        )
        .values(status=Event.status)
        .returning(Event.id)
    ).scalar_one_or_none()
    if claimed is None:
        return None
    event = db.get(Event, event_id)
    run = db.get(LotteryRun, event_id)
    if (
        event
        and event.status == "review"
        and db.scalar(
            select(Announcement.id)
            .where(Announcement.event_id == event_id, Announcement.kind == "assignment")
            .limit(1)
        )
    ):
        return None
    return (event, run) if event is not None and run is not None else None
