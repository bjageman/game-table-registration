"""Shared table scope for organizer signup and placement edits."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EventTableRemoval


def removals(db: Session, event_id: str) -> set[tuple[str, str]]:
    return {
        (row.discord_id, row.table_name)
        for row in db.scalars(
            select(EventTableRemoval).where(EventTableRemoval.event_id == event_id)
        )
    }


def set_removed(
    db: Session, event_id: str, player_id: str, table: str, removed: bool
) -> None:
    existing = db.get(EventTableRemoval, (event_id, player_id, table))
    if removed and existing is None:
        db.add(
            EventTableRemoval(event_id=event_id, discord_id=player_id, table_name=table)
        )
    elif not removed and existing is not None:
        db.delete(existing)


def filter_rows(
    db: Session, event_id: str, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    excluded = removals(db, event_id)
    return [
        {
            **row,
            "players": [
                p for p in row["players"] if (p["id"], row["name"]) not in excluded
            ],
        }
        for row in rows
    ]
