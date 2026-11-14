"""Publish a saved draw exactly once after any required organizer review."""

from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.discord.announcements import enqueue
from app.models import Announcement, Event, LotteryRun, PlayerProfile
from app.players.player_profiles import for_event as player_scope_for_event


def adjust_weights(db: Session, event: Event, run: LotteryRun) -> None:
    """Apply the completed draw once, under the event transition lock."""
    from app.assignments.withdrawals import current_result

    snapshot: dict[str, Any] = run.snapshot
    result: dict[str, Any] = current_result(db, run)
    if snapshot.get("automatic_weight_adjustment", True):
        profiles = {
            p.discord_id: p
            for p in db.scalars(
                select(PlayerProfile)
                .where(*player_scope_for_event(event).filters())
                .order_by(PlayerProfile.discord_id)
                .with_for_update()
            )
        }
        for player in snapshot["players"]:
            profile = profiles.get(player["id"])
            if profile is None:
                profile = PlayerProfile(
                    scope_key=player_scope_for_event(event).key,
                    guild_id=event.guild_id,
                    discord_id=player["id"],
                    discord_name=player["name"],
                    weighting=5.0,
                    is_test=bool(player.get("is_test")),
                )
                db.add(profile)
            delta = Decimal("-0.5" if player["id"] in result["assignments"] else "0.5")
            profile.weighting = float(
                min(
                    Decimal("10"),
                    max(Decimal("0.1"), Decimal(str(profile.weighting)) + delta),
                )
            )


def finalize(db: Session, event: Event, run: LotteryRun, channel_id: str = "") -> None:
    """Immediate publication when organizer review is disabled."""
    from app.assignments.withdrawals import current_result

    adjust_weights(db, event, run)
    event.status = "assigned"
    enqueue(
        db, event, event.channel_id or channel_id, current_result(db, run), run.snapshot
    )


def complete_review_delivery(db: Session, event_id: str) -> None:
    rows = list(
        db.scalars(
            select(Announcement).where(
                Announcement.event_id == event_id, Announcement.kind == "assignment"
            )
        )
    )
    if not rows or any(row.state != "sent" for row in rows):
        return
    claimed = db.execute(
        update(Event)
        .where(
            Event.id == event_id, Event.status == "review", Event.archived_at.is_(None)
        )
        .values(status="assigned")
        .returning(Event.id)
    ).scalar_one_or_none()
    if claimed:
        event = db.get(Event, event_id)
        run = db.get(LotteryRun, event_id)
        if event and run:
            adjust_weights(db, event, run)


def approve(engine: Engine, event_id: str, channel_id: str = "") -> None:
    with Session(engine) as db:
        claimed = db.execute(
            update(Event)
            .where(
                Event.id == event_id,
                Event.status.in_(["review", "assigned"]),
                Event.archived_at.is_(None),
            )
            .values(status=Event.status)
            .returning(Event.id)
        ).scalar_one_or_none()
        if claimed is None:
            raise HTTPException(409, "No assignments are awaiting review")
        event = db.get(Event, event_id)
        run = db.get(LotteryRun, event_id)
        if event is None or run is None:
            raise HTTPException(503, "Saved placements are unavailable")
        if event.status == "review":
            from app.assignments.withdrawals import current_result

            existing = db.scalar(
                select(Announcement.id)
                .where(
                    Announcement.event_id == event_id, Announcement.kind == "assignment"
                )
                .limit(1)
            )
            if existing is None:
                enqueue(
                    db,
                    event,
                    event.channel_id or channel_id,
                    current_result(db, run),
                    run.snapshot,
                )
            else:
                db.execute(
                    update(Announcement)
                    .where(
                        Announcement.event_id == event_id,
                        Announcement.kind == "assignment",
                        Announcement.state.in_(["pending", "needs_review"]),
                        Announcement.unknown.is_(False),
                        Announcement.token.is_(None),
                    )
                    .values(state="pending", next_attempt=0, error=None)
                )
            complete_review_delivery(db, event_id)
        db.commit()
