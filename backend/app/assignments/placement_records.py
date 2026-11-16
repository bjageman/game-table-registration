"""Persist roster changes inside the caller's locked event transaction."""

from sqlalchemy.orm import Session

from app.models import EventManualAssignment, EventWaitlistAddition, EventWithdrawal


def record_manual_assignment(
    db: Session, event_id: str, player_id: str, table_name: str, assigned_at: float
) -> None:
    assignment = db.get(EventManualAssignment, (event_id, player_id))
    if assignment is None:
        assignment = EventManualAssignment(event_id=event_id, discord_id=player_id)
        db.add(assignment)
    assignment.table_name = table_name
    assignment.assigned_at = assigned_at


def record_waitlist_addition(
    db: Session,
    event_id: str,
    player_id: str,
    table_name: str,
    name: str,
    added_at: float,
) -> None:
    addition = db.get(EventWaitlistAddition, (event_id, player_id, table_name))
    if addition is None:
        addition = EventWaitlistAddition(
            event_id=event_id,
            discord_id=player_id,
            table_name=table_name,
        )
        db.add(addition)
    addition.discord_name = name
    addition.added_at = added_at


def record_withdrawal(
    db: Session,
    event_id: str,
    player_id: str,
    table_name: str,
    withdrawn_at: float,
    promoted_id: str | None,
) -> None:
    """Keep prior replacement seats when a rejoined player withdraws again."""
    previous = db.get(EventWithdrawal, (event_id, player_id))
    if previous is None:
        db.add(
            EventWithdrawal(
                event_id=event_id,
                discord_id=player_id,
                table_name=table_name,
                withdrawn_at=withdrawn_at,
                promoted_id=promoted_id,
            )
        )
        return
    if previous.promoted_id:
        replacement = db.get(EventManualAssignment, (event_id, previous.promoted_id))
        if replacement is None or replacement.assigned_at < previous.withdrawn_at:
            record_manual_assignment(
                db,
                event_id,
                previous.promoted_id,
                previous.table_name,
                previous.withdrawn_at,
            )
    previous.table_name = table_name
    previous.withdrawn_at = withdrawn_at
    previous.promoted_id = promoted_id
