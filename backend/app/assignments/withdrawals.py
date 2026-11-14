"""Process post-assignment withdrawals and promote the table waitlist."""

import time
from typing import Any

from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.assignments.mutations import locked_assignment
from app.assignments.notifications import enqueue_table_change
from app.discord.announcements import enqueue_refresh
from app.discord.discord_format import clean
from app.discord.event_threads import queue_member
from app.discord.promotion_dms import enqueue as enqueue_promotion_dm
from app.models import (
    Announcement,
    Event,
    EventManagerSignup,
    EventManualAssignment,
    EventWaitlistAddition,
    EventWithdrawal,
    LotteryRun,
)
from app.players.player_profiles import for_event as player_scope_for_event


def announcement_event(
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


def result_players(db: Session, run: LotteryRun) -> dict[str, Any]:
    players = {player["id"]: player for player in run.snapshot["players"]}
    for signup in db.scalars(
        select(EventManagerSignup).where(EventManagerSignup.event_id == run.event_id)
    ):
        players.setdefault(
            signup.discord_id,
            {"id": signup.discord_id, "name": signup.discord_name},
        )
    for addition in db.scalars(
        select(EventWaitlistAddition).where(
            EventWaitlistAddition.event_id == run.event_id
        )
    ):
        players.setdefault(
            addition.discord_id,
            {"id": addition.discord_id, "name": addition.discord_name},
        )
    return players


def current_result(db: Session, run: LotteryRun) -> dict[str, Any]:
    result = run.result
    rows = list(
        db.scalars(
            select(EventWithdrawal)
            .where(EventWithdrawal.event_id == run.event_id)
            .order_by(EventWithdrawal.withdrawn_at, EventWithdrawal.discord_id)
        )
    )
    withdrawn = {row.discord_id: row.withdrawn_at for row in rows}
    assignments = {
        player_id: table
        for player_id, table in result["assignments"].items()
        if player_id not in withdrawn
    }
    manual = list(
        db.scalars(
            select(EventManualAssignment)
            .where(EventManualAssignment.event_id == run.event_id)
            .order_by(
                EventManualAssignment.assigned_at, EventManualAssignment.discord_id
            )
        )
    )
    placements = [
        (row.withdrawn_at, row.promoted_id, row.table_name)
        for row in rows
        if row.promoted_id
    ] + [(row.assigned_at, row.discord_id, row.table_name) for row in manual]
    for placed_at, player_id, table_name in sorted(placements):
        if placed_at > withdrawn.get(player_id, float("-inf")):
            assignments[player_id] = table_name

    additions = list(
        db.scalars(
            select(EventWaitlistAddition)
            .where(EventWaitlistAddition.event_id == run.event_id)
            .order_by(
                EventWaitlistAddition.added_at,
                EventWaitlistAddition.discord_id,
                EventWaitlistAddition.table_name,
            )
        )
    )
    by_id = result_players(db, run)
    tables = []
    for table in result["tables"]:
        name = table["name"]
        players = [
            dict(player)
            for player in table["players"]
            if assignments.get(player["id"]) == name
        ]
        included = {player["id"] for player in players}
        for player_id, table_name in assignments.items():
            if table_name == name and player_id not in included:
                player = by_id[player_id]
                players.append({"id": player_id, "name": player["name"]})
        # A rejoining player belongs at the end, never at their original rank.
        waitlist = [
            player
            for player in table.get("waitlist", [])
            if player["id"] not in withdrawn
        ]
        waitlist.extend(
            {"id": addition.discord_id, "name": addition.discord_name}
            for addition in additions
            if addition.table_name == name
            and addition.added_at > withdrawn.get(addition.discord_id, float("-inf"))
        )
        tables.append(
            {
                **table,
                "players": players,
                "waitlist": [
                    dict(player)
                    for player in waitlist
                    if player["id"] not in assignments
                ],
            }
        )
    return {
        **result,
        "pairing_warnings": [
            conflict["message"]
            for conflict in result.get("pairing_conflicts", [])
            if not all(pid in assignments for pid in conflict["players"])
        ],
        "assignments": assignments,
        "waitlist": list(
            dict.fromkeys(
                [
                    *[
                        player_id
                        for player_id in result["waitlist"]
                        if player_id not in withdrawn and player_id not in assignments
                    ],
                    *[
                        addition.discord_id
                        for addition in additions
                        if addition.added_at
                        > withdrawn.get(addition.discord_id, float("-inf"))
                        and addition.discord_id not in assignments
                    ],
                ]
            )
        ),
        "tables": tables,
    }


def record_withdrawal(
    db: Session,
    event_id: str,
    player_id: str,
    table_name: str,
    withdrawn_at: float,
    promoted_id: str | None,
) -> None:
    """Keep prior replacement seats when a rejoined player withdraws again."""
    previous = db.get(EventWithdrawal, (event_id, player_id))
    if previous is None:
        db.add(
            EventWithdrawal(
                event_id=event_id,
                discord_id=player_id,
                table_name=table_name,
                withdrawn_at=withdrawn_at,
                promoted_id=promoted_id,
            )
        )
        return
    if previous.promoted_id:
        replacement = db.get(EventManualAssignment, (event_id, previous.promoted_id))
        if replacement is None:
            db.add(
                EventManualAssignment(
                    event_id=event_id,
                    discord_id=previous.promoted_id,
                    table_name=previous.table_name,
                    assigned_at=previous.withdrawn_at,
                )
            )
        elif replacement.assigned_at < previous.withdrawn_at:
            replacement.table_name = previous.table_name
            replacement.assigned_at = previous.withdrawn_at
    previous.table_name = table_name
    previous.withdrawn_at = withdrawn_at
    previous.promoted_id = promoted_id


def withdraw(
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
        changed = withdraw_seat(db, event, run, player_id, channel_id)
        db.commit()
        return changed


def replace_with_waitlist(
    db: Session,
    event: Event,
    run: LotteryRun,
    current: dict[str, Any],
    player_id: str,
    table_name: str,
    changed_at: float,
) -> list[str]:
    from app.assignments.pair_promotions import replacements

    chosen = replacements(event, current, table_name)
    record_withdrawal(
        db,
        event.id,
        player_id,
        table_name,
        changed_at,
        chosen[0][0] if chosen else None,
    )
    for pid, table in chosen[1:]:
        placement = db.get(EventManualAssignment, (event.id, pid))
        if placement is None:
            db.add(
                EventManualAssignment(
                    event_id=event.id,
                    discord_id=pid,
                    table_name=table,
                    assigned_at=changed_at,
                )
            )
        else:
            placement.table_name = table
            placement.assigned_at = changed_at
    return [pid for pid, _ in chosen]


def promoted_names(db: Session, run: LotteryRun, ids: list[str]) -> str:
    players = result_players(db, run)
    return " and ".join(
        clean(players[pid]["name"]) if pid.startswith("test-") else f"<@{pid}>"
        for pid in ids
    )


def pair_promotion_text(db: Session, run: LotteryRun, ids: list[str]) -> str:
    """A split promotion must name each player's actual destination table."""
    current = current_result(db, run)
    return " ".join(
        f"{promoted_names(db, run, [pid])} has been promoted from the waitlist "
        f"to **{clean(current['assignments'][pid])}**."
        for pid in ids
    )


def notify_promoted(db: Session, event: Event, run: LotteryRun, ids: list[str]) -> None:
    if not ids or event.status != "assigned":
        return
    db.flush()
    assignments = current_result(db, run)["assignments"]
    for pid in ids:
        enqueue_promotion_dm(db, event, pid, assignments[pid])


def withdraw_seat(
    db: Session, event: Event, run: LotteryRun, player_id: str, channel_id: str
) -> bool:
    """Mutate a seat while the caller holds the event lock; commit with its work."""
    event_id = event.id
    current = current_result(db, run)
    table_name = current["assignments"].get(player_id)
    if table_name is None:
        return False

    withdrawn_at = time.time()
    promoted_ids = replace_with_waitlist(
        db, event, run, current, player_id, table_name, withdrawn_at
    )
    promoted_id = promoted_ids[0] if promoted_ids else None
    if promoted_id:
        left = result_players(db, run)[player_id]
        promoted_name = promoted_names(db, run, promoted_ids)
        left_name = (
            clean(left["name"]) if player_id.startswith("test-") else f"<@{player_id}>"
        )
        content = (
            f"{promoted_name} has been promoted to **{clean(table_name)}** "
            f"after {left_name} left their seat.\n"
        )
        if len(promoted_ids) > 1:
            content = pair_promotion_text(db, run, promoted_ids)
        enqueue_table_change(
            db,
            event,
            content,
            [*promoted_ids, player_id],
            nonce_key=f"{event_id}:promotion:{player_id}:{withdrawn_at}",
            created_at=withdrawn_at,
            channel_id=channel_id,
        )
    notify_promoted(db, event, run, promoted_ids)
    enqueue_refresh(db, event)
    return True


def manager_remove(
    engine: Engine, guild_id: str, event_id: str, player_id: str
) -> bool:
    """Remove a player, promoting from the waitlist unless the table is overfull."""
    with Session(engine) as db:
        locked = locked_assignment(db, guild_id, event_id)
        if locked is None:
            return False
        event, run = locked
        current = current_result(db, run)
        table_name = current["assignments"].get(player_id)
        if table_name is None:
            table_name = next(
                (
                    table["name"]
                    for table in current["tables"]
                    if any(player["id"] == player_id for player in table["waitlist"])
                ),
                None,
            )
            if table_name is None:
                return False
            removed_at = time.time()
            record_withdrawal(db, event.id, player_id, table_name, removed_at, None)
            if event.status == "assigned":
                enqueue_refresh(db, event)
            db.commit()
            return True
        removed_at = time.time()
        promoted_ids = replace_with_waitlist(
            db, event, run, current, player_id, table_name, removed_at
        )
        promoted_id = promoted_ids[0] if promoted_ids else None
        left = result_players(db, run)[player_id]
        left_name = (
            clean(left["name"]) if player_id.startswith("test-") else f"<@{player_id}>"
        )
        if promoted_id:
            promoted_name = promoted_names(db, run, promoted_ids)
            content = (
                f"{promoted_name} has been promoted from the waitlist "
                f"to **{clean(table_name)}**."
            )
            if len(promoted_ids) > 1:
                content = pair_promotion_text(db, run, promoted_ids)
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
        notify_promoted(db, event, run, promoted_ids)
        if event.status == "assigned":
            enqueue_refresh(db, event)
        db.commit()
        return True


def manager_add(
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
        locked = locked_assignment(db, guild_id, event_id)
        if locked is None:
            return False
        event, run = locked
        current = current_result(db, run)
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
        if (
            not waitlisted
            and db.get(EventWithdrawal, (event_id, player_id)) is not None
        ):
            return False
        profile = player_scope_for_event(event).get(db, player_id)
        known = result_players(db, run)
        if not waitlisted and profile is None:
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
        assignment = db.get(EventManualAssignment, (event_id, player_id))
        if assignment is None:
            db.add(
                EventManualAssignment(
                    event_id=event_id,
                    discord_id=player_id,
                    table_name=table_name,
                    assigned_at=time.time(),
                )
            )
        else:
            assignment.table_name = table_name
            assignment.assigned_at = time.time()
        queue_member(db, event, player_id)
        if event.status == "assigned":
            action = "promoted from the waitlist" if waitlisted else "added"
            promoted = known[player_id]
            name = (
                clean(promoted["name"])
                if player_id.startswith("test-")
                else f"<@{player_id}>"
            )
            enqueue_table_change(
                db,
                event,
                f"{name} has been {action} to **{clean(table_name)}**.",
                [player_id],
                nonce_key=f"{event_id}:manager-add:{player_id}",
                created_at=time.time(),
            )
        if was_waitlisted:
            notify_promoted(db, event, run, [player_id])
        if event.status == "assigned":
            enqueue_refresh(db, event)
        db.commit()
        return True
