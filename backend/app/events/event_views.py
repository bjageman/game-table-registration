"""Batch related event data and preserve the event API presentation contract."""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.events.signup_warnings import settings as warning_settings
from app.models import Announcement, DiscordScheduledEvent, Event


@dataclass
class EventRelatedData:
    scheduled: dict[str, DiscordScheduledEvent] = field(default_factory=dict)
    delivery: dict[str, list[Announcement]] = field(default_factory=dict)

    @classmethod
    def load(cls, db: Session, events: list[Event]) -> "EventRelatedData":
        data = cls()
        if not events:
            return data
        event_ids = [event.id for event in events]
        data.scheduled = {
            row.event_id: row
            for row in db.scalars(
                select(DiscordScheduledEvent).where(
                    DiscordScheduledEvent.event_id.in_(event_ids)
                )
            )
        }
        review_ids = [event.id for event in events if event.status == "review"]
        if review_ids:
            for row in db.scalars(
                select(Announcement).where(
                    Announcement.event_id.in_(review_ids),
                    Announcement.kind == "assignment",
                )
            ):
                data.delivery.setdefault(row.event_id, []).append(row)
        return data


def serialize_event(
    event: Event, fallback_channel_id: str, related: EventRelatedData
) -> dict[str, Any]:
    discord_event = related.scheduled.get(event.id)
    delivery = related.delivery.get(event.id, [])
    return {
        **warning_settings(event),
        "auto_promote_waitlist": event.auto_promote_waitlist,
        "id": event.id,
        "title": event.title,
        "description": event.description,
        "location": event.location,
        "starts_at": event.starts_at,
        "created_at": event.created_at,
        "ends_at": event.ends_at,
        "discord_event_error": discord_event.error if discord_event else None,
        "has_discord_event": bool(discord_event and discord_event.state != "deleted"),
        "duration_hours": event.duration_hours,
        "tables": event.tables,
        "status": event.status,
        "assignment_publication_pending": bool(delivery),
        "assignment_publication_error": next(
            (row.error for row in delivery if row.error), None
        ),
        "signup_mode": event.signup_mode,
        "closes_at": event.closes_at
        if event.closes_at is not None
        else event.scheduled_publish_at + event.duration_hours * 3600
        if event.series_id and event.scheduled_publish_at is not None
        else None,
        "published_at": event.published_at,
        "series_id": event.series_id,
        "scheduled_publish_at": event.scheduled_publish_at,
        "archived_at": event.archived_at,
        "signup_deleted_at": event.signup_deleted_at,
        "close_error": event.close_error or event.reaction_error,
        "is_test": bool(event.test_signups),
        "test_generation": event.test_signups.get("generation")
        if event.test_signups
        else None,
        "test_user_count": len(event.test_signups["players"])
        if event.test_signups
        else 0,
        "discord_url": (
            f"https://discord.com/channels/{event.guild_id}/"
            f"{event.channel_id or fallback_channel_id}/"
            f"{event.message_id}"
        )
        if event.message_id and not event.signup_deleted_at
        else None,
    }
