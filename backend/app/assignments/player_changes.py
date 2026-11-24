"""Apply player seating, waitlist, and withdrawal changes under an event lock."""

import logging
import time
from typing import Any

from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.assignments.notifications import (
    enqueue_promotion_dms,
    enqueue_table_change,
    format_pair_promotion,
    format_roster_players,
)
from app.assignments.placement_records import (
    record_manual_assignment,
    record_waitlist_addition,
    record_withdrawal,
)
from app.assignments.roster import (
    build_current_roster,
    build_roster_players,
    roster_order,
)
from app.assignments.waitlist_guarantees import update_guarantees
from app.discord.discord_format import clean
from app.discord.event_messages import enqueue_roster_refresh
from app.discord.event_threads import queue_member
from app.discord.promotion_dms import enqueue as enqueue_seat_dm
from app.events.table_membership import set_removed
from app.models import (
    Announcement,
    Event,
    EventManagerSignup,
    EventWithdrawal,
    LotteryRun,
    PromotionDM,
)
from app.players.player_profiles import for_event as player_scope_for_event

logger = logging.getLogger("uvicorn.error")


def lock_assignment_for_edit(
    db: Session, guild_id: str, event_id: str
) -> tuple[Event, LotteryRun] | None:
    """Keep this transaction open through the edits and notification outbox writes."""
    claimed = db.execute(
        update(Event)
        .where(
            Event.id == event_id,
            Event.guild_id == guild_id,
            Event.status.in_(["assigned", "review"]),
            Event.archived_at.is_(None),
        )
        .values(status=Event.status)
        .returning(Event.id)
    ).scalar_one_or_none()
    if claimed is None:
        return None
    event = db.get(Event, event_id)
    run = db.get(LotteryRun, event_id)
    if (
        event
        and event.status == "review"
        and db.scalar(
            select(Announcement.id)
            .where(Announcement.event_id == event_id, Announcement.kind == "assignment")
            .limit(1)
        )
    ):
        return None
    return (event, run) if event is not None and run is not None else None


def event_for_withdrawal_message(
    engine: Engine, guild_id: str, channel_id: str, message_id: str
) -> str | None:
    with Session(engine) as db:
        return db.scalar(
            select(Event.id)
            .join(Announcement, Announcement.event_id == Event.id)
            .where(
                Event.guild_id == guild_id,
                Event.status == "assigned",
                Event.archived_at.is_(None),
                Event.starts_at > time.time(),
                Announcement.channel_id == channel_id,
                Announcement.message_id == message_id,
                Announcement.kind.in_(["assignment", "promotion", "instructions"]),
                Announcement.state == "sent",
                Announcement.deleted_at.is_(None),
            )
        )


def select_waitlist_replacements(
    event: Event, current: dict[str, Any], table_name: str
) -> list[tuple[str, str]]:
    """Choose replacements in waitlist order, preserving pair and guarantee rules."""
    if not event.auto_promote_waitlist:
        return []
    tables = {row["name"]: row for row in current["tables"]}
    free = {
        row["name"]: row["capacity"]
        - len(tables[row["name"]]["players"])
        + int(row["name"] == table_name)
        for row in event.tables
    }
    waiting = set(current["waitlist"])
    pairs = current.get("pairs", {})
    blocked = {
        pid
        for conflict in current.get("pairing_conflicts", [])
        for pid in conflict["players"]
    }
    for candidate in tables[table_name]["waitlist"]:
        pid = candidate["id"]
        partner = pairs.get(pid)
        if pid in blocked or (partner and partner in blocked):
            continue
        if not partner or partner not in waiting:
            if free[table_name] >= 1:
                return [(pid, table_name)]
            continue
        eligible = [
            name
            for name, row in tables.items()
            if any(player["id"] == partner for player in row["waitlist"])
        ]
        if table_name in eligible and free[table_name] >= 2:
            return [(pid, table_name), (partner, table_name)]
        if pid not in current.get("pair_guarantees", []):
            for other in sorted(eligible):
                if other != table_name and free[table_name] >= 1 and free[other] >= 1:
                    return [(pid, table_name), (partner, other)]
    return []


def withdraw_from_announcement(
    engine: Engine,
    guild_id: str,
    channel_id: str,
    message_id: str,
    player_id: str,
) -> bool:
    with Session(engine) as db:
        announcement = db.scalar(
            select(Announcement)
            .join(Event, Event.id == Announcement.event_id)
            .where(
                Event.guild_id == guild_id,
                Event.status == "assigned",
                Event.archived_at.is_(None),
                Event.starts_at > time.time(),
                Announcement.channel_id == channel_id,
                Announcement.message_id == message_id,
                Announcement.kind.in_(["assignment", "promotion", "instructions"]),
                Announcement.state == "sent",
                Announcement.deleted_at.is_(None),
            )
        )
        if announcement is None:
            return False
        event_id = announcement.event_id
        claimed = db.execute(
            update(Event)
            .where(
                Event.id == event_id,
                Event.guild_id == guild_id,
                Event.status == "assigned",
                Event.archived_at.is_(None),
                Event.starts_at > time.time(),
            )
            .values(status=Event.status)
            .returning(Event.id)
        ).scalar_one_or_none()
        if claimed is None:
            return False
        event = db.get(Event, event_id)
        run = db.get(LotteryRun, event_id)
        if event is None or run is None:
            return False
        changed = withdraw_player_seat(db, event, run, player_id, channel_id)
        db.commit()
        return changed


def _replace_with_waitlist(
    db: Session,
    event: Event,
    run: LotteryRun,
    current: dict[str, Any],
    player_id: str,
    table_name: str,
    changed_at: float,
) -> list[str]:

    chosen = select_waitlist_replacements(event, current, table_name)
    if event.status == "assigned" and chosen:
        update_guarantees(
            db,
            event,
            build_roster_players(db, run),
            seated=[pid for pid, _ in chosen],
            promotion_times={pid: changed_at for pid, _ in chosen},
        )
    order = roster_order(current["tables"], "players")
    for name, ids in order.items():
        order[name] = [pid for pid in ids if pid != player_id] + [
            pid for pid, destination in chosen if destination == name
        ]
    run.seat_order = order
    record_withdrawal(
        db,
        event.id,
        player_id,
        table_name,
        changed_at,
        chosen[0][0] if chosen else None,
    )
    for pid, table in chosen[1:]:
        record_manual_assignment(db, event.id, pid, table, changed_at)
    return [pid for pid, _ in chosen]


def withdraw_player_seat(
    db: Session, event: Event, run: LotteryRun, player_id: str, channel_id: str
) -> bool:
    """Mutate a seat while the caller holds the event lock; commit with its work."""
    event_id = event.id
    current = build_current_roster(db, run)
    table_name = current["assignments"].get(player_id)
    if table_name is None:
        return False

    withdrawn_at = time.time()
    promoted_ids = _replace_with_waitlist(
        db, event, run, current, player_id, table_name, withdrawn_at
    )
    promoted_id = promoted_ids[0] if promoted_ids else None
    if promoted_id:
        known = build_roster_players(db, run)
        promoted_name = format_roster_players(known, promoted_ids)
        left_name = format_roster_players(known, [player_id])
        content = (
            f"{promoted_name} has been promoted to **{clean(table_name)}** "
            f"after {left_name} left their seat.\n"
        )
        if len(promoted_ids) > 1:
            content = format_pair_promotion(db, run, promoted_ids)
        enqueue_table_change(
            db,
            event,
            content,
            [*promoted_ids, player_id],
            nonce_key=f"{event_id}:promotion:{player_id}:{withdrawn_at}",
            created_at=withdrawn_at,
            channel_id=channel_id,
        )
    enqueue_promotion_dms(db, event, run, promoted_ids)
    enqueue_roster_refresh(db, event)
    return True


def remove_player_from_roster(
    engine: Engine,
    guild_id: str,
    event_id: str,
    player_id: str,
    table_name: str | None = None,
    *,
    waitlist_only: bool = False,
) -> bool:
    """Remove a player, promoting from the waitlist unless the table is overfull."""
    with Session(engine) as db:
        locked = lock_assignment_for_edit(db, guild_id, event_id)
        if locked is None:
            return False
        event, run = locked
        current = build_current_roster(db, run)
        requested_table = table_name
        seated_table = current["assignments"].get(player_id)
        table_name = (
            seated_table
            if not waitlist_only
            and (requested_table is None or requested_table == seated_table)
            else None
        )
        if table_name is None:
            table_name = next(
                (
                    table["name"]
                    for table in current["tables"]
                    if (requested_table is None or table["name"] == requested_table)
                    and any(player["id"] == player_id for player in table["waitlist"])
                ),
                None,
            )
            if table_name is None:
                return False
            set_removed(db, event.id, player_id, table_name, True)
            if event.status == "assigned":
                enqueue_roster_refresh(db, event)
            db.commit()
            return True
        removed_at = time.time()
        promoted_ids = _replace_with_waitlist(
            db, event, run, current, player_id, table_name, removed_at
        )
        promoted_id = promoted_ids[0] if promoted_ids else None
        known = build_roster_players(db, run)
        left_name = format_roster_players(known, [player_id])
        if promoted_id:
            promoted_name = format_roster_players(known, promoted_ids)
            content = (
                f"{promoted_name} has been promoted from the waitlist "
                f"to **{clean(table_name)}**."
            )
            if len(promoted_ids) > 1:
                content = format_pair_promotion(db, run, promoted_ids)
            mentions = [pid for pid in promoted_ids if not pid.startswith("test-")]
        else:
            content = f"{left_name} has left their seat at **{clean(table_name)}**."
            mentions = [] if player_id.startswith("test-") else [player_id]
        enqueue_table_change(
            db,
            event,
            content,
            mentions,
            nonce_key=f"{event_id}:manager-removal:{player_id}:{removed_at}",
            created_at=removed_at,
        )
        enqueue_promotion_dms(db, event, run, promoted_ids)
        if event.status == "assigned":
            enqueue_roster_refresh(db, event)
        db.commit()
        return True


def assign_player_to_table(
    engine: Engine,
    guild_id: str,
    event_id: str,
    player_id: str,
    table_name: str,
    *,
    allow_known_player: bool = False,
) -> bool:
    """Assign a waitlisted or explicitly selected known player, even to a full table."""
    with Session(engine) as db:
        locked = lock_assignment_for_edit(db, guild_id, event_id)
        if locked is None:
            return False
        event, run = locked
        current = build_current_roster(db, run)
        table = next(
            (row for row in current["tables"] if row["name"] == table_name), None
        )
        if table is None:
            return False
        waitlisted = player_id in {p["id"] for p in table["waitlist"]}
        was_waitlisted = player_id in current["waitlist"]
        if not waitlisted and not allow_known_player:
            return False
        if player_id in current["assignments"]:
            return False
        profile = player_scope_for_event(event).get(db, player_id)
        known = build_roster_players(db, run)
        if not waitlisted and profile is None and player_id not in known:
            return False
        if player_id not in known:
            assert profile is not None
            override = db.get(EventManagerSignup, (event_id, player_id))
            if override is None:
                db.add(
                    EventManagerSignup(
                        event_id=event_id,
                        discord_id=player_id,
                        discord_name=profile.discord_name,
                        choices=[table_name],
                        removed=False,
                    )
                )
            else:
                override.discord_name = profile.discord_name
                override.choices = [table_name]
                override.removed = False
            known[player_id] = {"id": player_id, "name": profile.discord_name}
        previous_withdrawal = db.get(EventWithdrawal, (event_id, player_id))
        assigned_at = max(
            time.time(),
            previous_withdrawal.withdrawn_at + 0.000001 if previous_withdrawal else 0,
        )
        if event.status == "assigned":
            update_guarantees(
                db,
                event,
                known,
                seated=[player_id],
                promotion_times={player_id: assigned_at} if was_waitlisted else {},
            )
        order = roster_order(current["tables"], "players")
        order[table_name].append(player_id)
        run.seat_order = order
        record_manual_assignment(db, event_id, player_id, table_name, assigned_at)
        set_removed(db, event_id, player_id, table_name, False)
        queue_member(db, event, player_id)
        if event.status == "assigned":
            action = "promoted from the waitlist" if waitlisted else "added"
            name = format_roster_players(known, [player_id])
            enqueue_table_change(
                db,
                event,
                f"{name} has been {action} to **{clean(table_name)}**.",
                [player_id],
                nonce_key=f"{event_id}:manager-add:{player_id}:{assigned_at}",
                created_at=time.time(),
            )
        if was_waitlisted:
            enqueue_promotion_dms(db, event, run, [player_id])
        elif event.status == "assigned":
            enqueue_seat_dm(db, event, player_id, table_name, kind="assignment")
        if event.status == "assigned":
            enqueue_roster_refresh(db, event)
        db.commit()
        return True


def add_player_to_waitlist(
    engine: Engine, guild_id: str, event_id: str, player_id: str, table_name: str
) -> bool:
    with Session(engine) as db:
        locked = lock_assignment_for_edit(db, guild_id, event_id)
        if locked is None:
            return False
        event, run = locked
        profile = player_scope_for_event(event).get(db, player_id)
        known = build_roster_players(db, run).get(player_id)
        if profile is None and known is None:
            return False
        current = build_current_roster(db, run)
        table = next(
            (row for row in current["tables"] if row["name"] == table_name), None
        )
        if (
            table is None
            or player_id in current["assignments"]
            or any(player["id"] == player_id for player in table["waitlist"])
            or (
                player_id.startswith("test-")
                and profile is not None
                and not profile.is_test
            )
        ):
            return False
        if profile is not None:
            name = profile.discord_name
        else:
            assert known is not None
            name = known["name"]
        if event.status == "assigned":
            update_guarantees(
                db, event, {player_id: {"name": name}}, waitlisted=[player_id]
            )
        record_waitlist_addition(db, event_id, player_id, table_name, name, time.time())
        run.waitlist_order = {
            name: [pid for pid in ids if pid != player_id]
            if name == table_name
            else ids
            for name, ids in run.waitlist_order.items()
        }
        set_removed(db, event_id, player_id, table_name, False)
        queue_member(db, event, player_id)
        if event.status == "assigned":
            enqueue_roster_refresh(db, event)
        db.commit()
        return True


def withdraw_from_promotion_dm(
    engine: Engine, notice_id: str, user_id: str, channel_id: str, message_id: str
) -> str:
    """Only the intended recipient may relinquish a current, future seat."""

    with Session(engine) as db:
        notice = db.get(PromotionDM, notice_id)
        context = (notice_id, user_id, channel_id, message_id)
        reasons = (
            ["notice_not_found"]
            if notice is None
            else [
                reason
                for reason, failed in (
                    ("recipient_mismatch", notice.discord_id != user_id),
                    ("notice_not_sent", notice.state != "sent"),
                    ("channel_mismatch", notice.channel_id != channel_id),
                    ("message_mismatch", notice.message_id != message_id),
                )
                if failed
            ]
        )
        if reasons:
            logger.warning(
                "Promotion DM withdrawal rejected reason=%s "
                "notice_id=%s user_id=%s channel_id=%s message_id=%s "
                "event_id=%s expected_user_id=%s expected_channel_id=%s "
                "expected_message_id=%s notice_state=%s attempts=%s unknown=%s",
                ",".join(reasons),
                *context,
                notice.event_id if notice else None,
                notice.discord_id if notice else None,
                notice.channel_id if notice else None,
                notice.message_id if notice else None,
                notice.state if notice else None,
                notice.attempts if notice else None,
                notice.unknown if notice else None,
            )
            return "Something went wrong. Please contact the host for assistance."
        assert notice is not None
        claimed = db.execute(
            update(Event)
            .where(
                Event.id == notice.event_id,
                Event.status == "assigned",
                Event.archived_at.is_(None),
                Event.starts_at > time.time(),
            )
            .values(status=Event.status)
            .returning(Event.id)
        ).scalar_one_or_none()
        if claimed is None:
            event = db.get(Event, notice.event_id)
            logger.warning(
                "Promotion DM withdrawal rejected reason=event_not_accepting "
                "notice_id=%s user_id=%s channel_id=%s message_id=%s "
                "event_id=%s event_status=%s archived_at=%s starts_at=%s now=%s",
                *context,
                notice.event_id,
                event.status if event else None,
                event.archived_at if event else None,
                event.starts_at if event else None,
                time.time(),
            )
            return "This event has started or is no longer accepting withdrawals."
        event = db.get(Event, notice.event_id)
        run = db.get(LotteryRun, notice.event_id)
        if event is None or run is None:
            logger.warning(
                "Promotion DM withdrawal rejected reason=event_or_draw_missing "
                "notice_id=%s user_id=%s channel_id=%s message_id=%s "
                "event_id=%s event_exists=%s draw_exists=%s",
                *context,
                notice.event_id,
                event is not None,
                run is not None,
            )
            return "This event is no longer available."
        if not withdraw_player_seat(db, event, run, user_id, event.channel_id or ""):
            logger.info(
                "Promotion DM withdrawal unchanged reason=no_current_seat "
                "notice_id=%s user_id=%s channel_id=%s message_id=%s event_id=%s",
                *context,
                notice.event_id,
            )
            return "You no longer have a seat at this event."
        db.commit()
        logger.info(
            "Promotion DM withdrawal completed "
            "notice_id=%s user_id=%s channel_id=%s message_id=%s event_id=%s",
            *context,
            notice.event_id,
        )
        return (
            f"You have withdrawn from {clean(event.title)}. "
            "Your seat is now available to the next waitlisted player."
        )
