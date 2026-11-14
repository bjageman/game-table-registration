"""Publication services shared by API routes and workers."""

import time
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session as DBSession

from app.assignment_preferences import for_event as preferences_for_event
from app.context import ApplicationContext
from app.discord_api import DiscordAPI
from app.models import (
    Event,
)
from app.open_signup_rosters import with_initial_roster
from app.reactions import publication as reaction_publication
from app.signup_messages import EMOJIS, signup_body


def publish_event(
    context: ApplicationContext,
    event_id: str,
    discord: DiscordAPI,
    expected_status: str,
    force: bool = False,
) -> dict[str, Any]:
    app = context.app
    config = context.config
    engine = context.engine
    serialize = context.serialize
    with DBSession(engine) as db:
        event = db.get(Event, event_id)
        if not event:
            raise HTTPException(404, "Event not found")
        if event.duration_hours == 0 and config.discord_gateway_enabled:
            gateway = getattr(app.state, "gateway", None)
            if gateway is None or not gateway.is_ready():
                raise HTTPException(503, "Discord signup listener is not connected.")
        if (
            not force
            and expected_status == "scheduled"
            and event.scheduled_publish_at is not None
        ):
            if event.scheduled_publish_at > time.time():
                raise HTTPException(409, "Publication is not due yet")
            if event.scheduled_publish_at + event.duration_hours * 3600 <= time.time():
                event.status = "needs_review"
                event.close_error = "The signup window passed before publication."
                db.commit()
                raise HTTPException(409, event.close_error)
        if (event.closes_at is not None and event.closes_at <= time.time()) or (
            event.closes_at is None
            and event.starts_at <= time.time() + event.duration_hours * 3600
        ):
            if expected_status == "scheduled":
                event.status = "needs_review"
                event.close_error = "Too late to publish the signup window."
                db.commit()
                raise HTTPException(409, event.close_error)
            raise HTTPException(400, "Signup window would end after the event starts")
        claimed = db.execute(
            update(Event)
            .where(Event.id == event_id, Event.status == expected_status)
            .values(
                status="publishing",
                signup_mode=(
                    "reactions"
                    if config.discord_signup_mode == "custom"
                    or event.duration_hours == 0
                    else "poll"
                ),
            )
            .returning(Event.id)
        ).scalar_one_or_none()
        db.commit()
        if not claimed:
            raise HTTPException(409, "Already published or awaiting publish review")
        db.refresh(event)
        try:
            closes_at = event.closes_at or (
                event.scheduled_publish_at + event.duration_hours * 3600
                if event.scheduled_publish_at
                else time.time() + event.duration_hours * 3600
                if event.duration_hours
                else None
            )
            assignment_preferences = preferences_for_event(db, event)
            include_roster = bool(
                assignment_preferences
                and assignment_preferences.show_open_signup_players
            )
            payload = (
                reaction_publication(event, closes_at, include_roster)
                if event.signup_mode == "reactions"
                else {
                    **signup_body(event, "poll", closes_at, include_roster),
                    "allowed_mentions": {"parse": []},
                    "poll": {
                        "question": {"text": "Which tables would you attend?"},
                        "answers": [
                            {
                                "poll_media": {
                                    "text": f"{t['name']} · {t['capacity']} seats"
                                }
                            }
                            for t in event.tables
                        ],
                        "duration": event.duration_hours,
                        "allow_multiselect": True,
                    },
                }
            )
            message = discord.publish(with_initial_roster(db, event, payload))
            event.published_at = (
                datetime.fromisoformat(message["timestamp"]).timestamp()
                if message.get("timestamp")
                else time.time()
            )
            event.message_id = str(message["id"])
            event.series_id = None
            if event.signup_mode == "reactions":
                event.closes_at = closes_at
                # Save the message identity before seeding: an uncertain PUT
                # must never cause a second publication on retry.
                db.commit()
                discord.seed_reactions(
                    event.message_id, list(EMOJIS[: len(event.tables)])
                )
            else:
                event.answers = message["poll"]["answers"]
                event.closes_at = (
                    event.closes_at
                    or datetime.fromisoformat(message["poll"]["expiry"]).timestamp()
                )
            event.status = "open"
            db.commit()
        except Exception:
            db.rollback()
            db.execute(
                update(Event).where(Event.id == event_id).values(status="needs_review")
            )
            db.commit()
            raise HTTPException(
                502,
                "Publish could not be confirmed. Check Discord "
                "before retrying; this event is held for review.",
            ) from None
        return serialize(event)


def mark_signup_closed(discord: DiscordAPI, message_id: str, mode: str) -> None:
    if mode == "reactions":
        discord.close_reaction_message(message_id)
    else:
        discord.close_signup_message(message_id)
