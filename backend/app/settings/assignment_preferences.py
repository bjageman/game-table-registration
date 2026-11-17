"""Assignment options scoped to a selected organization or personal events."""

from sqlalchemy.orm import Session

from app.models import AssignmentPreference, Event
from app.settings.general_settings import GeneralSettingsValues


def for_scope(db: Session, key: str) -> AssignmentPreference:
    return db.get(AssignmentPreference, key) or AssignmentPreference(
        scope_key=key, **GeneralSettingsValues().model_dump()
    )


def scope_key(organization_id: str | None, user_id: str) -> str:
    return f"org:{organization_id}" if organization_id else f"user:{user_id}"


def for_event(db: Session, event: Event) -> AssignmentPreference:
    return for_scope(db, scope_key(event.organization_id, event.created_by))


def announce_changes(db: Session, event: Event) -> bool:
    saved = for_event(db, event)
    return saved.announce_table_changes
