"""Shared leases and transport mechanics for durable Discord message delivery."""

import secrets
from typing import Any

from sqlalchemy import or_, update
from sqlalchemy.orm import Session

from app.discord.discord_api import DiscordAPI, DiscordRequestError
from app.models import Announcement, PromotionDM

MessageModel = type[Announcement] | type[PromotionDM]
DELIVERY_LEASE_SECONDS = 90
UNCONFIRMED_DELIVERY = "Delivery could not be confirmed. Check Discord before retrying."


def claim_delivery(
    db: Session, model: MessageModel, row_id: str, *, now: float, attempted_at: float
) -> str | None:
    """Claim atomically; the caller retains its transaction and eligibility checks."""
    token = secrets.token_hex(16)
    claimed = db.execute(
        update(model)
        .where(
            model.id == row_id,
            model.state.in_(["pending", "sending"]),
            or_(model.token.is_(None), model.lease_until <= now),
        )
        .values(
            state="sending",
            token=token,
            lease_until=now + DELIVERY_LEASE_SECONDS,
            attempts=model.attempts + 1,
            attempted_at=attempted_at,
        )
        .returning(model.id)
    ).scalar_one_or_none()
    return token if claimed else None


def save_delivery(
    db: Session, model: MessageModel, row_id: str, lease_token: str, **values: Any
) -> None:
    """Persist results only while this worker still owns the delivery lease."""
    db.execute(
        update(model)
        .where(model.id == row_id, model.token == lease_token)
        .values(**values)
    )


def complete_delivery(
    db: Session,
    model: MessageModel,
    row_id: str,
    token: str,
    message_id: str | None,
    *,
    deleted_at: float | None = None,
) -> None:
    values: dict[str, Any] = {
        "state": "sent",
        "message_id": message_id,
        "unknown": False,
        "token": None,
        "lease_until": None,
        "error": None,
    }
    if model is Announcement:
        values["deleted_at"] = deleted_at
    save_delivery(db, model, row_id, token, **values)


def resolve_message(
    discord: DiscordAPI,
    channel_id: str,
    payload: dict[str, Any],
    attempted_at: float,
    *,
    unknown: bool,
) -> str | None:
    """Reconcile an uncertain send without issuing another message POST."""
    if unknown:
        return discord.find_announcement(channel_id, payload, attempted_at)
    return str(discord.send_announcement(channel_id, payload)["id"])


def delivery_is_uncertain(failure: Exception, *, unknown: bool, sending: bool) -> bool:
    return unknown or (
        sending and (not isinstance(failure, DiscordRequestError) or failure.ambiguous)
    )


def retry_delay(failure: Exception, attempts: int) -> float:
    retry_after = failure.retry_after if isinstance(failure, DiscordRequestError) else 0
    return float(max(retry_after, min(3600, 5 * 2 ** min(attempts, 10))))


def announcement_failure_values(
    failure: Exception, *, unknown: bool, sending: bool, attempts: int, now: float
) -> dict[str, Any]:
    """Public-message policy; DM eligibility and terminal states stay with DMs."""
    uncertain = delivery_is_uncertain(failure, unknown=unknown, sending=sending)
    state = "needs_review" if unknown else "pending"
    if isinstance(failure, DiscordRequestError) and failure.discord_status == 400:
        state = "needs_review"
    error = (
        UNCONFIRMED_DELIVERY
        if uncertain
        else "Discord rejected the announcement. Use Retry Announcement to try again."
        if state == "needs_review"
        else "Discord could not accept the announcement. Automatic retry is queued."
    )
    return {
        "state": state,
        "error": error,
        "unknown": uncertain,
        "token": None,
        "lease_until": None,
        "next_attempt": now + retry_delay(failure, attempts),
    }
