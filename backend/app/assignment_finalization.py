"""Publish a saved draw exactly once after any required organizer review."""

from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.announcements import enqueue
from app.models import Event, LotteryRun, PlayerProfile
from app.player_profiles import for_event as player_scope_for_event


def finalize(db: Session, event: Event, run: LotteryRun, channel_id: str = "") -> None:
    """Called only by the transaction that owns the event's state transition."""
    from app.withdrawals import current_result

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
    event.status = "assigned"
    enqueue(db, event, event.channel_id or channel_id, result, snapshot)


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
            finalize(db, event, run, channel_id)
        db.commit()
