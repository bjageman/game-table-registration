"""Claim editable assignment state within the caller's transaction."""

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import Event, LotteryRun


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
    return (event, run) if event is not None and run is not None else None
