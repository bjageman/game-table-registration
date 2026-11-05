"""Assignment options scoped to a selected organization or personal events."""

from sqlalchemy.orm import Session

from app.models import AssignmentPreference, Event


def scope_key(organization_id: str | None, user_id: str) -> str:
    return f"org:{organization_id}" if organization_id else f"user:{user_id}"


def for_event(db: Session, event: Event) -> AssignmentPreference | None:
    return db.get(
        AssignmentPreference, scope_key(event.organization_id, event.created_by)
    )


def announce_changes(db: Session, event: Event) -> bool:
    saved = for_event(db, event)
    return saved.announce_table_changes if saved else False
