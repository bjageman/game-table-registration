import time
from datetime import datetime

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Engine, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.discord_api import DiscordAPI
from app.models import Event
from app.reconciliation import answer_mapping


class RecoveryInput(BaseModel):
    message_id: str | None = Field(default=None, pattern=r"^[0-9]{1,32}$")
    accept_late_votes: bool = False
    reason: str = Field(min_length=10, max_length=300)

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value: str) -> str:
        if len(value.strip()) < 10:
            raise ValueError("Give a recovery reason of at least 10 characters")
        return value.strip()


def recover_event(
    engine: Engine,
    discord: DiscordAPI,
    config: Settings,
    event_id: str,
    body: RecoveryInput,
    actor: str,
) -> None:
    claimed_at = time.time()
    with Session(engine) as db:
        claimed = db.execute(
            update(Event)
            .where(
                Event.id == event_id,
                Event.guild_id == config.discord_guild_id,
                Event.status == "needs_review",
            )
            .values(status="recovering", operation_started_at=claimed_at)
            .returning(Event.id)
        ).scalar_one_or_none()
        db.commit()
        if not claimed:
            raise HTTPException(409, "Only events awaiting review can be recovered")
        event = db.get(Event, event_id)
        assert event is not None
        try:
            message_id = body.message_id or event.message_id
            if not message_id:
                raise ValueError(
                    "Provide the existing poll message ID; recovery never reposts"
                )
            message = discord.bot(
                "GET", f"/channels/{config.discord_channel_id}/messages/{message_id}"
            )
            bot = discord.bot("GET", "/users/@me")
            if message.get("author", {}).get("id") != bot.get("id") or not bot.get(
                "id"
            ):
                raise ValueError("Poll must be owned by this Discord bot")
            if (
                event.message_id != message_id
                and f"Event ID: {event.id}" not in message.get("content", "")
            ):
                raise ValueError(
                    "Poll does not contain this event's recovery identifier"
                )
            poll = message.get("poll", {})
            answer_mapping(event, poll)
            expiry = datetime.fromisoformat(poll["expiry"]).timestamp()
            deadline = event.signup_closes_at or expiry
            now = time.time()
            uncertain = now > deadline and expiry > deadline
            if uncertain and not body.accept_late_votes:
                raise ValueError(
                    "Deadline missed; accept later votes explicitly or keep it held"
                )
            if now >= deadline and expiry > now:
                discord.bot(
                    "POST",
                    f"/channels/{config.discord_channel_id}/polls/{message_id}/expire",
                )
            status = "closed" if now >= deadline else "open"
            audit = [
                *(event.recovery_audit or []),
                {
                    "actor": actor,
                    "at": now,
                    "reason": body.reason,
                    "message_id": message_id,
                    "accepted_late_votes": uncertain and body.accept_late_votes,
                },
            ]
            changed = db.execute(
                update(Event)
                .where(
                    Event.id == event_id,
                    Event.status == "recovering",
                    Event.operation_started_at == claimed_at,
                )
                .values(
                    message_id=message_id,
                    answers=poll["answers"],
                    closes_at=expiry,
                    status=status,
                    recovery_audit=audit,
                    last_error=None,
                    operation_started_at=None,
                    reconcile_after=None,
                )
                .returning(Event.id)
            ).scalar_one_or_none()
            if not changed:
                raise ValueError("Recovery claim expired; refresh before retrying")
            db.commit()
        except Exception as failure:
            db.rollback()
            db.execute(
                update(Event)
                .where(
                    Event.id == event_id,
                    Event.status == "recovering",
                    Event.operation_started_at == claimed_at,
                )
                .values(
                    status="needs_review",
                    last_error=str(failure)[:500],
                    operation_started_at=None,
                )
            )
            db.commit()
            raise HTTPException(409, str(failure)) from None
