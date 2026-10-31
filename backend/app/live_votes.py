from sqlalchemy import Engine, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Event, LiveVote


def record_vote(
    engine: Engine,
    guild_id: str,
    message_id: str,
    user_id: str,
    answer_id: int,
    added: bool,
) -> None:
    with Session(engine) as db:
        event = db.scalar(
            select(Event).where(
                Event.guild_id == guild_id,
                Event.message_id == message_id,
                Event.status == "open",
            )
        )
        if not event or answer_id not in {a["answer_id"] for a in event.answers or []}:
            return
        if not added:
            db.execute(
                delete(LiveVote).where(
                    LiveVote.event_id == event.id,
                    LiveVote.user_id == user_id,
                    LiveVote.answer_id == answer_id,
                )
            )
            db.commit()
        elif db.get(LiveVote, (event.id, user_id, answer_id)) is None:
            db.add(LiveVote(event_id=event.id, user_id=user_id, answer_id=answer_id))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
