"""Update profile guarantees for finalized waitlists and seating changes."""

import time
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assignments.roster import (
    build_current_roster,
    build_roster_players,
    load_roster_records,
)
from app.models import Event, LotteryRun, PlayerProfile
from app.players.player_profiles import for_event as player_scope_for_event
from app.settings.assignment_preferences import for_event


def update_guarantees(
    db: Session,
    event: Event,
    players: dict[str, Any],
    *,
    waitlisted: Iterable[str] = (),
    seated: Iterable[str] = (),
    promotion_times: dict[str, float] | None = None,
) -> None:
    """Apply changes under the event lock; the caller commits with its roster edit."""
    waiting, assigned = set(waitlisted), set(seated)
    ids = waiting | assigned
    if not ids:
        return
    settings = for_event(db, event)
    if not settings.guarantee_waitlisted_players:
        return
    scope = player_scope_for_event(event)
    scope.lock(db)
    profiles = {
        p.discord_id: p
        for p in db.scalars(
            select(PlayerProfile)
            .where(*scope.filters(), PlayerProfile.discord_id.in_(ids))
            .order_by(PlayerProfile.discord_id)
            .with_for_update()
        )
    }
    for pid in sorted(ids):
        profile = profiles.get(pid)
        if profile is None:
            player = players[pid]
            profile = scope.create(
                pid,
                discord_name=player["name"],
                is_test=pid.startswith("test-") or bool(player.get("is_test")),
            )
            db.add(profile)
        promoted_at = (promotion_times or {}).get(pid)
        keep_for_late_promotion = (
            promoted_at is not None
            and settings.keep_waitlist_guarantee_on_short_notice
            and event.starts_at - promoted_at
            <= settings.waitlist_guarantee_retention_hours * 3600
        )
        profile.guaranteed_seat = pid in waiting or keep_for_late_promotion


def finalize_guarantees(db: Session, event: Event, run: LotteryRun) -> None:
    """Only finalize real results; reviewing a provisional draw changes no profiles."""
    if not for_event(db, event).guarantee_waitlisted_players:
        return
    records = load_roster_records(db, [event.id])[event.id]
    current = build_current_roster(db, run, records=records)
    promotion_times: dict[str, float] = {}
    for row in records.manual:
        promotion_times[row.discord_id] = row.assigned_at
    for withdrawal in records.withdrawals:
        if withdrawal.promoted_id:
            pid = withdrawal.promoted_id
            promotion_times[pid] = max(
                promotion_times.get(pid, 0), withdrawal.withdrawn_at
            )
    original_waitlist = set(run.result["waitlist"])
    original_waitlist.update(row.discord_id for row in records.additions)
    update_guarantees(
        db,
        event,
        build_roster_players(db, run, records=records),
        waitlisted=current["waitlist"],
        seated=current["assignments"],
        promotion_times={
            pid: promotion_times.get(pid, time.time())
            for pid in original_waitlist
            if pid in current["assignments"]
        },
    )
