"""Format and queue public table changes and private promotion notices."""

import hashlib
import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.assignments.roster import build_current_roster, build_roster_players
from app.discord.discord_format import clean, is_discord_user_id, player_reference
from app.discord.promotion_dms import enqueue as enqueue_promotion_dm
from app.models import Announcement, Event, LotteryRun
from app.settings.assignment_preferences import announce_changes


def enqueue_table_change(
    db: Session,
    event: Event,
    content: str,
    recipients: Iterable[str],
    *,
    nonce_key: str,
    created_at: float,
    channel_id: str | None = None,
) -> None:
    """The caller holds the assignment mutation lock and commits the outbox."""
    if event.status != "assigned" or not announce_changes(db, event):
        return
    channel = (
        event.channel_id
        or channel_id
        or db.scalar(
            select(Announcement.channel_id)
            .where(Announcement.event_id == event.id)
            .order_by(Announcement.part)
            .limit(1)
        )
    )
    if not channel:
        return
    part = db.scalar(
        select(func.max(Announcement.part)).where(Announcement.event_id == event.id)
    )
    db.add(
        Announcement(
            id=str(uuid.uuid4()),
            event_id=event.id,
            part=(part if part is not None else -1) + 1,
            kind="promotion",
            channel_id=channel,
            payload={
                "content": content,
                "allowed_mentions": {
                    "parse": [],
                    "users": [pid for pid in recipients if is_discord_user_id(pid)],
                },
                "nonce": hashlib.sha256(nonce_key.encode()).hexdigest()[:24],
                "enforce_nonce": True,
            },
            created_at=created_at,
            next_attempt=created_at,
        )
    )


def format_roster_players(players: dict[str, Any], ids: list[str]) -> str:
    """Use safe names for test players and mentions for Discord players."""
    return " and ".join(player_reference(players[pid]) for pid in ids)


def format_pair_promotion(db: Session, run: LotteryRun, ids: list[str]) -> str:
    """A split promotion must name each player's actual destination table."""
    current = build_current_roster(db, run)
    players = build_roster_players(db, run)
    return " ".join(
        f"{format_roster_players(players, [pid])} "
        "has been promoted from the waitlist "
        f"to **{clean(current['assignments'][pid])}**."
        for pid in ids
    )


def enqueue_promotion_dms(
    db: Session, event: Event, run: LotteryRun, ids: list[str]
) -> None:
    if not ids or event.status != "assigned":
        return
    db.flush()
    assignments = build_current_roster(db, run)["assignments"]
    for pid in ids:
        enqueue_promotion_dm(db, event, pid, assignments[pid])
