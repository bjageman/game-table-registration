"""Resolve a selected organization only while the user remains a member."""

from sqlalchemy.orm import Session

from app.models import Organization, OrganizationMember, OrganizationSelection


def selected_organization(
    db: Session, user_id: str
) -> tuple[Organization | None, OrganizationMember | None]:
    selection = db.get(OrganizationSelection, user_id)
    organization = (
        db.get(Organization, selection.organization_id) if selection else None
    )
    if organization is None:
        return None, None
    member = db.get(OrganizationMember, (organization.id, user_id))
    return (organization, member) if member else (None, None)
