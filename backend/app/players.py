import time
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Event, Withdrawal


def player_status(
    engine: Engine, guild_id: str, user_id: str, event_id: str
) -> dict[str, Any]:
    with Session(engine) as db:
        event = db.get(Event, event_id)
        if not event or event.guild_id != guild_id:
            raise HTTPException(404, "Event not found in this server")
        withdrawn = db.get(Withdrawal, (event_id, user_id)) is not None
        selected: list[str] = next(
            (
                entry["tables"]
                for entry in event.voter_snapshot or []
                if entry["user_id"] == user_id
            ),
            [],
        )
        return {
            "title": event.title,
            "status": event.status,
            "withdrawn": withdrawn,
            "tables": selected,
            "reconciled": event.reconciled_at is not None,
        }


def withdraw(engine: Engine, guild_id: str, user_id: str, event_id: str) -> None:
    with Session(engine) as db:
        event = db.scalar(
            select(Event)
            .where(Event.id == event_id, Event.guild_id == guild_id)
            .with_for_update()
        )
        if not event:
            raise HTTPException(404, "Event not found in this server")
        if event.status not in (
            "open",
            "closing",
            "closed",
            "reconciling",
            "reconciled",
            "needs_review",
        ):
            raise HTTPException(409, "This event is not accepting withdrawals")
        if db.get(Withdrawal, (event_id, user_id)):
            return
        db.add(Withdrawal(event_id=event_id, user_id=user_id, created_at=time.time()))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
