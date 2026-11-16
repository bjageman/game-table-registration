"""Preferences API routes."""

import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session as DBSession

from app.assignments.player_changes import lock_assignment_for_edit
from app.assignments.roster import build_current_roster
from app.assignments.waitlist_guarantees import update_guarantees
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
            enable_guarantees = body.guarantee_waitlisted_players and not (
                previous and previous.guarantee_waitlisted_players
            )
            db.merge(
                AssignmentPreference(
                    scope_key=assignment_scope_key(
                        request.state.organization_id, session.user_id
                    ),
                    **body.model_dump(),
                )
            )
            scope = (
                Event.organization_id == request.state.organization_id
                if request.state.organization_id
                else (Event.organization_id.is_(None))
                & (Event.created_by == session.user_id)
            )
            if roster_changed:
                db.execute(
                    update(Event)
                    .where(scope, Event.status == "open")
                    .values(signup_roster_checked_at=None)
                )
            if enable_guarantees:
                candidates = list(
                    db.execute(
                        select(Event.id, Event.guild_id)
                        .where(
                            scope,
                            Event.status == "assigned",
                            Event.archived_at.is_(None),
                            Event.starts_at > time.time(),
                        )
                        .order_by(Event.id)
                    )
                )
                for event_id, guild in candidates:
                    locked = lock_assignment_for_edit(db, guild, event_id)
                    if locked is None:
                        continue
                    event, run = locked
                    waiting = {
                        p["id"]: p
                        for row in build_current_roster(db, run)["tables"]
                        for p in row["waitlist"]
                    }
                    update_guarantees(db, event, waiting, waitlisted=waiting)
            db.commit()
        return body.model_dump()

    context.app.include_router(router)
