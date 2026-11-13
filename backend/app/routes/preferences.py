"""Preferences API routes."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import update
from sqlalchemy.orm import Session as DBSession

from app.assignment_preferences import scope_key as assignment_scope_key
from app.context import ApplicationContext
from app.models import (
    AssignmentPreference,
    Event,
)
from app.schemas import (
    AssignmentSettingsInput,
)


def register(context: ApplicationContext) -> None:
    router = APIRouter()
    authenticated = context.authenticated
    engine = context.engine

    @router.get("/api/settings/assignment")
    def assignment_settings(request: Request) -> dict[str, Any]:
        session = authenticated(request, require_destination=False)
        key = assignment_scope_key(request.state.organization_id, session.user_id)
        with DBSession(engine) as db:
            saved = db.get(AssignmentPreference, key)
            return {
                "automatic_weight_adjustment": saved.automatic_weight_adjustment
                if saved
                else True,
                "announce_table_changes": saved.announce_table_changes
                if saved
                else False,
                "post_discord_updates_to_thread": saved.post_discord_updates_to_thread
                if saved
                else False,
                "timezone": saved.timezone if saved else None,
                "show_open_signup_players": saved.show_open_signup_players
                if saved
                else False,
            }

    @router.put("/api/settings/assignment")
    def save_assignment_settings(
        body: AssignmentSettingsInput, request: Request
    ) -> dict[str, Any]:
        session = authenticated(request, True, require_destination=False)
        if request.state.organization_id and request.state.organization_role != "admin":
            raise HTTPException(
                403, "Only organization admins can save assignment settings"
            )
        with DBSession(engine) as db:
            key = assignment_scope_key(request.state.organization_id, session.user_id)
            previous = db.get(AssignmentPreference, key)
            if "timezone" not in body.model_fields_set and previous:
                body.timezone = previous.timezone
            if "show_open_signup_players" not in body.model_fields_set and previous:
                body.show_open_signup_players = previous.show_open_signup_players
            roster_changed = (
                bool(previous and previous.show_open_signup_players)
                != body.show_open_signup_players
            )
            db.merge(
                AssignmentPreference(
                    scope_key=assignment_scope_key(
                        request.state.organization_id, session.user_id
                    ),
                    automatic_weight_adjustment=body.automatic_weight_adjustment,
                    announce_table_changes=body.announce_table_changes,
                    post_discord_updates_to_thread=body.post_discord_updates_to_thread,
                    timezone=body.timezone,
                    show_open_signup_players=body.show_open_signup_players,
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
