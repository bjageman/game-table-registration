"""Organizations API routes."""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.context import ApplicationContext
from app.models import (
    Event,
    Organization,
    OrganizationMember,
    OrganizationSelection,
    UserIdentity,
)
from app.schemas import (
    OrganizationInput,
    OrganizationMemberInput,
    OrganizationSelectionInput,
)


def register(context: ApplicationContext) -> None:
    router = APIRouter()
    authenticated = context.authenticated
    engine = context.engine

    def organization_data(
        db: DBSession, org: Organization, user_id: str
    ) -> dict[str, Any]:
        member = db.get(OrganizationMember, (org.id, user_id))
        return {
            "id": org.id,
            "name": org.name,
            "created_by": org.created_by,
            "role": member.role if member else None,
        }

    @router.get("/api/organizations")
    def organizations(request: Request) -> dict[str, Any]:
        session = authenticated(request, require_destination=False)
        with DBSession(engine) as db:
            memberships = db.scalars(
                select(OrganizationMember).where(
                    OrganizationMember.user_id == session.user_id
                )
            ).all()
            selected = db.get(OrganizationSelection, session.user_id)
            return {
                "selected_id": selected.organization_id if selected else None,
                "organizations": [
                    organization_data(db, org, session.user_id)
                    for membership in memberships
                    if (org := db.get(Organization, membership.organization_id))
                    is not None
                ],
            }

    @router.post("/api/organizations", status_code=201)
    def create_organization(
        body: OrganizationInput, request: Request
    ) -> dict[str, Any]:
        session = authenticated(request, True, require_destination=False)
        name = body.name.strip()
        if not name or len(name.casefold()) > 100:
            raise HTTPException(422, "Choose a name of up to 100 characters")
        with DBSession(engine) as db:
            org = Organization(
                id=str(uuid.uuid4()),
                name=name,
                normalized_name=name.casefold(),
                created_by=session.user_id,
                guild_id="",
                channel_id="",
            )
            db.add(org)
            db.add(
                OrganizationMember(
                    organization_id=org.id, user_id=session.user_id, role="admin"
                )
            )
            try:
                db.commit()
            except IntegrityError:
                raise HTTPException(
                    409, "Organization name is already in use"
                ) from None
            return organization_data(db, org, session.user_id)

    @router.put("/api/organizations/selection")
    def select_organization(
        body: OrganizationSelectionInput, request: Request
    ) -> dict[str, Any]:
        session = authenticated(request, True, require_destination=False)
        with DBSession(engine) as db:
            if (
                body.organization_id
                and db.get(OrganizationMember, (body.organization_id, session.user_id))
                is None
            ):
                raise HTTPException(403, "You are not a member of this organization")
            if body.organization_id:
                db.merge(
                    OrganizationSelection(
                        user_id=session.user_id, organization_id=body.organization_id
                    )
                )
            else:
                db.execute(
                    delete(OrganizationSelection).where(
                        OrganizationSelection.user_id == session.user_id
                    )
                )
            db.commit()
        return {"ok": True}

    @router.get("/api/organizations/users")
    def find_organization_users(request: Request, q: str = "") -> list[dict[str, str]]:
        session = authenticated(request, require_destination=False)
        if len(q.strip()) < 2:
            return []
        with DBSession(engine) as db:
            if not db.scalar(
                select(OrganizationMember.organization_id)
                .where(
                    OrganizationMember.user_id == session.user_id,
                    OrganizationMember.role == "admin",
                )
                .limit(1)
            ):
                raise HTTPException(403, "Admin access required")
            pattern = f"%{q.strip().casefold()}%"
            return [
                {"id": user.id, "username": user.username}
                for user in db.scalars(
                    select(UserIdentity)
                    .where(
                        func.lower(UserIdentity.username).like(pattern)
                        | UserIdentity.id.like(pattern)
                    )
                    .limit(20)
                )
            ]

    def require_org_admin(db: DBSession, org_id: str, user_id: str) -> Organization:
        org = db.get(Organization, org_id)
        member = db.get(OrganizationMember, (org_id, user_id))
        if org is None or member is None or member.role != "admin":
            raise HTTPException(403, "Organization admin access required")
        return org

    @router.get("/api/organizations/{org_id}/members")
    def organization_members(org_id: str, request: Request) -> list[dict[str, str]]:
        session = authenticated(request, require_destination=False)
        with DBSession(engine) as db:
            if db.get(OrganizationMember, (org_id, session.user_id)) is None:
                raise HTTPException(403, "Organization membership required")
            members = db.scalars(
                select(OrganizationMember).where(
                    OrganizationMember.organization_id == org_id
                )
            ).all()
            return [
                {
                    "user_id": member.user_id,
                    "username": (
                        identity.username
                        if (identity := db.get(UserIdentity, member.user_id))
                        else member.user_id
                    ),
                    "role": member.role,
                }
                for member in members
            ]

    @router.put("/api/organizations/{org_id}/members/{user_id}")
    def save_organization_member(
        org_id: str, user_id: str, body: OrganizationMemberInput, request: Request
    ) -> dict[str, str]:
        session = authenticated(request, True, require_destination=False)
        if body.user_id != user_id or body.role not in ("user", "editor", "admin"):
            raise HTTPException(422, "Invalid member or permission")
        with DBSession(engine) as db:
            org = require_org_admin(db, org_id, session.user_id)
            if user_id == org.created_by:
                raise HTTPException(403, "Creator permissions cannot be changed")
            if db.get(UserIdentity, user_id) is None:
                raise HTTPException(404, "User not found")
            db.merge(
                OrganizationMember(
                    organization_id=org_id, user_id=user_id, role=body.role
                )
            )
            db.commit()
        return {"ok": "true"}

    @router.delete("/api/organizations/{org_id}/members/me", status_code=204)
    def leave_organization(org_id: str, request: Request) -> Response:
        session = authenticated(request, True, require_destination=False)
        with DBSession(engine) as db:
            org = db.get(Organization, org_id)
            if (
                org is None
                or db.get(OrganizationMember, (org_id, session.user_id)) is None
            ):
                raise HTTPException(404, "Organization not found")
            if org.created_by == session.user_id:
                raise HTTPException(409, "Creator must delete the organization")
            db.execute(
                delete(OrganizationSelection).where(
                    OrganizationSelection.user_id == session.user_id,
                    OrganizationSelection.organization_id == org_id,
                )
            )
            db.execute(
                delete(OrganizationMember).where(
                    OrganizationMember.organization_id == org_id,
                    OrganizationMember.user_id == session.user_id,
                )
            )
            db.commit()
        return Response(status_code=204)

    @router.delete("/api/organizations/{org_id}/members/{user_id}", status_code=204)
    def remove_organization_member(
        org_id: str, user_id: str, request: Request
    ) -> Response:
        session = authenticated(request, True, require_destination=False)
        with DBSession(engine) as db:
            org = require_org_admin(db, org_id, session.user_id)
            if user_id == org.created_by:
                raise HTTPException(403, "The creator cannot be removed")
            if user_id == session.user_id:
                raise HTTPException(409, "Use Leave organization to remove yourself")
            member = db.get(OrganizationMember, (org_id, user_id))
            if member is None:
                raise HTTPException(404, "Organization member not found")
            db.execute(
                delete(OrganizationSelection).where(
                    OrganizationSelection.user_id == user_id,
                    OrganizationSelection.organization_id == org_id,
                )
            )
            db.delete(member)
            db.commit()
        return Response(status_code=204)

    @router.delete("/api/organizations/{org_id}", status_code=204)
    def delete_organization(org_id: str, request: Request) -> Response:
        session = authenticated(request, True, require_destination=False)
        with DBSession(engine) as db:
            org = db.get(Organization, org_id)
            if org is None or org.created_by != session.user_id:
                raise HTTPException(
                    403, "Only the creator can delete this organization"
                )
            db.execute(
                update(Event)
                .where(Event.organization_id == org_id)
                .values(organization_id=None)
            )
            db.execute(
                delete(OrganizationSelection).where(
                    OrganizationSelection.organization_id == org_id
                )
            )
            db.execute(
                delete(OrganizationMember).where(
                    OrganizationMember.organization_id == org_id
                )
            )
            db.delete(org)
            db.commit()
        return Response(status_code=204)

    context.app.include_router(router)
