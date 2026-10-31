import math
import time
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Engine, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.discord_api import DiscordAPI
from app.models import Event


def publish_event(
    engine: Engine,
    discord: DiscordAPI,
    config: Settings,
    event_id: str,
    scheduled: bool = False,
) -> None:
    now = time.time()
    with Session(engine) as db:
        event = db.get(Event, event_id)
        if not event or event.guild_id != config.discord_guild_id:
            raise HTTPException(404, "Event not found")
        if scheduled:
            if event.opens_at is None or event.opens_at > now:
                raise HTTPException(409, "Signup opening is not due")
            closing = event.signup_closes_at
            if closing is None or closing <= now or event.starts_at <= now:
                raise HTTPException(409, "Signup window has expired")
        else:
            if event.opens_at is not None:
                raise HTTPException(409, "Use Schedule signups for this draft")
            closing = now + event.duration_hours * 3600
        if event.starts_at <= closing:
            raise HTTPException(400, "Signup window must end before the event starts")
        claimed = db.execute(
            update(Event)
            .where(
                Event.id == event_id,
                Event.status == ("scheduled" if scheduled else "draft"),
            )
            .values(status="publishing", operation_started_at=now)
            .returning(Event.id)
        ).scalar_one_or_none()
        db.commit()
        if not claimed:
            raise HTTPException(409, "Already published or awaiting publish review")
        db.refresh(event)
        try:
            # Reload after claiming so concurrent committed draft edits are included.
            closing = (
                event.signup_closes_at
                if scheduled
                else time.time() + event.duration_hours * 3600
            )
            if closing is None or closing <= time.time() or closing >= event.starts_at:
                raise ValueError("Signup window expired before publication")
            duration = max(1, math.ceil((closing - time.time()) / 3600))
            payload: dict[str, Any] = {
                "content": (
                    f"**{event.title}**\nEvent: <t:{int(event.starts_at)}:F>\n"
                    f"Signups close: <t:{int(closing)}:F>\n"
                    "Select every table you would attend. "
                    "This is a lottery entry, not a guaranteed seat."
                ),
                "allowed_mentions": {"parse": []},
                "poll": {
                    "question": {"text": "Which tables would you attend?"},
                    "answers": [
                        {"poll_media": {"text": f"{t['name']} · {t['capacity']} seats"}}
                        for t in event.tables
                    ],
                    "duration": duration,
                    "allow_multiselect": True,
                },
            }
            message = discord.publish(payload)
            event.message_id = str(message["id"])
            event.answers = message["poll"]["answers"]
            event.closes_at = datetime.fromisoformat(
                message["poll"]["expiry"]
            ).timestamp()
            event.status = "open"
            event.operation_started_at = None
            db.commit()
        except Exception:
            db.rollback()
            db.execute(
                update(Event)
                .where(Event.id == event_id)
                .values(
                    status="needs_review",
                    last_error="Publication uncertain; check Discord before recovery.",
                )
            )
            db.commit()
            raise HTTPException(
                502,
                "Publish could not be confirmed. Check Discord before retrying; "
                "this event is held for review.",
            ) from None
