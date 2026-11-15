"""Preferences API routes."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import update
from sqlalchemy.orm import Session as DBSession

from app.context import ApplicationContext
from app.models import (
    AssignmentPreference,
    Event,
)
from app.settings.assignment_preferences import for_scope
from app.settings.assignment_preferences import scope_key as assignment_scope_key
from app.settings.general_settings import GeneralSettingsInput, settings_values


def register(context: ApplicationContext) -> None:
    router = APIRouter()
    authenticated = context.authenticated
    engine = context.engine

    @router.get("/api/settings/assignment")
    def general_settings(request: Request) -> dict[str, Any]:
        session = authenticated(request, require_destination=False)
        key = assignment_scope_key(request.state.organization_id, session.user_id)
        with DBSession(engine) as db:
            saved = for_scope(db, key)
            return settings_values(saved)

    @router.put("/api/settings/assignment")
    def save_general_settings(
        body: GeneralSettingsInput, request: Request
    ) -> dict[str, Any]:
        session = authenticated(request, True, require_destination=False)
        if request.state.organization_id and request.state.organization_role != "admin":
            raise HTTPException(
                403, "Only organization admins can save assignment settings"
            )
        with DBSession(engine) as db:
            key = assignment_scope_key(request.state.organization_id, session.user_id)
            previous = db.get(AssignmentPreference, key)
            for field in type(body).model_fields:
                if field not in body.model_fields_set and previous:
                    setattr(body, field, getattr(previous, field))
            roster_changed = (
                for_scope(db, key).show_open_signup_players
                != body.show_open_signup_players
            )
            db.merge(
                AssignmentPreference(
                    scope_key=assignment_scope_key(
                        request.state.organization_id, session.user_id
                    ),
                    **body.model_dump(),
                )
            )
            if roster_changed:
                scope = (
                    Event.organization_id == request.state.organization_id
                    if request.state.organization_id
                    else (Event.organization_id.is_(None))
                    & (Event.created_by == session.user_id)
                )
                db.execute(
                    update(Event)
                    .where(scope, Event.status == "open")
                    .values(signup_roster_checked_at=None)
                )
            db.commit()
        return body.model_dump()

    context.app.include_router(router)
