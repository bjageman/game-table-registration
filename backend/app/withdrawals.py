"""Process post-assignment withdrawals and promote the table waitlist."""

import hashlib
import time
import uuid
from typing import Any

from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session

from app.announcements import clean, enqueue_refresh
from app.assignment_preferences import announce_changes
from app.models import (
    Announcement,
    Event,
    EventManualAssignment,
    EventWithdrawal,
    LotteryRun,
)


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


def current_result(db: Session, run: LotteryRun) -> dict[str, Any]:
    result = run.result
    rows = list(
        db.scalars(
            select(EventWithdrawal)
            .where(EventWithdrawal.event_id == run.event_id)
            .order_by(EventWithdrawal.withdrawn_at, EventWithdrawal.discord_id)
        )
    )
    withdrawn = {row.discord_id for row in rows}
    assignments = {
        player_id: table
        for player_id, table in result["assignments"].items()
        if player_id not in withdrawn
    }
    for row in rows:
        if row.promoted_id and row.promoted_id not in withdrawn:
            assignments[row.promoted_id] = row.table_name
    manual = list(
        db.scalars(
            select(EventManualAssignment)
            .where(EventManualAssignment.event_id == run.event_id)
            .order_by(
                EventManualAssignment.assigned_at, EventManualAssignment.discord_id
            )
        )
    )
    for manual_row in manual:
        if manual_row.discord_id not in withdrawn:
            assignments[manual_row.discord_id] = manual_row.table_name

    by_id = {player["id"]: player for player in run.snapshot["players"]}
    tables = []
    for table in result["tables"]:
        name = table["name"]
        players = [
            dict(player)
            for player in table["players"]
            if assignments.get(player["id"]) == name
        ]
        included = {player["id"] for player in players}
        for row in rows:
            promoted = row.promoted_id
            if (
                row.table_name == name
                and promoted
                and assignments.get(promoted) == name
                and promoted not in included
            ):
                player = by_id[promoted]
                players.append({"id": promoted, "name": player["name"]})
                included.add(promoted)
        for manual_row in manual:
            if (
                manual_row.table_name == name
                and assignments.get(manual_row.discord_id) == name
                and manual_row.discord_id not in included
            ):
                player = by_id[manual_row.discord_id]
                players.append({"id": manual_row.discord_id, "name": player["name"]})
                included.add(manual_row.discord_id)
        tables.append(
            {
                **table,
                "players": players,
                "waitlist": [
                    dict(player)
                    for player in table.get("waitlist", [])
                    if player["id"] not in assignments and player["id"] not in withdrawn
                ],
            }
        )
    return {
        **result,
        "assignments": assignments,
        "waitlist": [
            player_id
            for player_id in result["waitlist"]
            if player_id not in assignments and player_id not in withdrawn
        ],
        "tables": tables,
    }


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
        current = current_result(db, run)
        table_name = current["assignments"].get(player_id)
        if table_name is None:
            return False

        table = next(
            table for table in run.result["tables"] if table["name"] == table_name
        )
        active_ids = set(current["assignments"])
        withdrawn_ids = set(
            db.scalars(
                select(EventWithdrawal.discord_id).where(
                    EventWithdrawal.event_id == event_id
                )
            )
        )
        promoted_id = next(
            (
                player["id"]
                for player in table.get("waitlist", [])
                if player["id"] not in active_ids and player["id"] not in withdrawn_ids
            ),
            None,
        )
        withdrawn_at = time.time()
        db.add(
            EventWithdrawal(
                event_id=event_id,
                discord_id=player_id,
                table_name=table_name,
                withdrawn_at=withdrawn_at,
                promoted_id=promoted_id,
            )
        )
        if promoted_id and announce_changes(db, event):
            left = next(
                player
                for player in run.snapshot["players"]
                if player["id"] == player_id
            )
            promoted = next(
                player
                for player in run.snapshot["players"]
                if player["id"] == promoted_id
            )
            promoted_name = (
                clean(promoted["name"])
                if promoted_id.startswith("test-")
                else f"<@{promoted_id}>"
            )
            left_name = (
                clean(left["name"])
                if player_id.startswith("test-")
                else f"<@{player_id}>"
            )
            announce_id = db.scalar(
                select(func.max(Announcement.part)).where(
                    Announcement.event_id == event_id
                )
            )
            part = (announce_id if announce_id is not None else -1) + 1
            content = (
                f"{promoted_name} has been promoted to **{clean(table_name)}** "
                f"after {left_name} left their seat.\n"
            )
            mentions = [
                user_id
                for user_id in (promoted_id, player_id)
                if not user_id.startswith("test-")
            ]
            db.add(
                Announcement(
                    id=str(uuid.uuid4()),
                    event_id=event_id,
                    part=part,
                    kind="promotion",
                    channel_id=event.channel_id or channel_id,
                    payload={
                        "content": content,
                        "allowed_mentions": {"parse": [], "users": mentions},
                        "nonce": hashlib.sha256(
                            f"{event_id}:promotion:{player_id}".encode()
                        ).hexdigest()[:24],
                        "enforce_nonce": True,
                    },
                    created_at=withdrawn_at,
                    next_attempt=withdrawn_at,
                )
            )
        enqueue_refresh(db, event)
        db.commit()
        return True


def manager_remove(
    engine: Engine, guild_id: str, event_id: str, player_id: str
) -> bool:
    """Remove a player, promoting from the waitlist unless the table is overfull."""
    with Session(engine) as db:
        claimed = db.execute(
            update(Event)
            .where(
                Event.id == event_id,
                Event.guild_id == guild_id,
                Event.status == "assigned",
                Event.archived_at.is_(None),
            )
            .values(status=Event.status)
            .returning(Event.id)
        ).scalar_one_or_none()
        if claimed is None:
            return False
        run = db.get(LotteryRun, event_id)
        if run is None:
            return False
        event = db.get(Event, event_id)
        if event is None:
            return False
        current = current_result(db, run)
        table_name = current["assignments"].get(player_id)
        if table_name is None:
            return False
        table = next(row for row in current["tables"] if row["name"] == table_name)
        capacity = next(
            row["capacity"] for row in event.tables if row["name"] == table_name
        )
        promoted_id = (
            table["waitlist"][0]["id"]
            if len(table["players"]) <= capacity and table["waitlist"]
            else None
        )
        removed_at = time.time()
        db.add(
            EventWithdrawal(
                event_id=event_id,
                discord_id=player_id,
                table_name=table_name,
                withdrawn_at=removed_at,
                promoted_id=promoted_id,
            )
        )
        left = next(
            player for player in run.snapshot["players"] if player["id"] == player_id
        )
        left_name = (
            clean(left["name"]) if player_id.startswith("test-") else f"<@{player_id}>"
        )
        if promoted_id:
            promoted_name = (
                clean(
                    next(
                        player["name"]
                        for player in run.snapshot["players"]
                        if player["id"] == promoted_id
                    )
                )
                if promoted_id.startswith("test-")
                else f"<@{promoted_id}>"
            )
            content = (
                f"{promoted_name} has been promoted from the waitlist "
                f"to **{clean(table_name)}**."
            )
            mentions = [] if promoted_id.startswith("test-") else [promoted_id]
        else:
            content = f"{left_name} has left their seat at **{clean(table_name)}**."
            mentions = [] if player_id.startswith("test-") else [player_id]
        channel_id = event.channel_id or db.scalar(
            select(Announcement.channel_id)
            .where(Announcement.event_id == event_id)
            .order_by(Announcement.part)
            .limit(1)
        )
        if channel_id and announce_changes(db, event):
            part = db.scalar(
                select(func.max(Announcement.part)).where(
                    Announcement.event_id == event_id
                )
            )
            db.add(
                Announcement(
                    id=str(uuid.uuid4()),
                    event_id=event_id,
                    part=(part if part is not None else -1) + 1,
                    kind="promotion",
                    channel_id=channel_id,
                    payload={
                        "content": content,
                        "allowed_mentions": {"parse": [], "users": mentions},
                        "nonce": hashlib.sha256(
                            f"{event_id}:manager-removal:{player_id}".encode()
                        ).hexdigest()[:24],
                        "enforce_nonce": True,
                    },
                    created_at=removed_at,
                    next_attempt=removed_at,
                )
            )
        enqueue_refresh(db, event)
        db.commit()
        return True


def manager_add(
    engine: Engine, guild_id: str, event_id: str, player_id: str, table_name: str
) -> bool:
    """Assign an available waitlisted player to a table, even when it is full."""
    with Session(engine) as db:
        claimed = db.execute(
            update(Event)
            .where(
                Event.id == event_id,
                Event.guild_id == guild_id,
                Event.status == "assigned",
                Event.archived_at.is_(None),
            )
            .values(status=Event.status)
            .returning(Event.id)
        ).scalar_one_or_none()
        if claimed is None:
            return False
        run = db.get(LotteryRun, event_id)
        if run is None:
            return False
        current = current_result(db, run)
        table = next(
            (row for row in current["tables"] if row["name"] == table_name), None
        )
        if table is None or player_id not in {p["id"] for p in table["waitlist"]}:
            return False
        if player_id in current["assignments"]:
            return False
        db.add(
            EventManualAssignment(
                event_id=event_id,
                discord_id=player_id,
                table_name=table_name,
                assigned_at=time.time(),
            )
        )
        event = db.get(Event, event_id)
        assert event is not None
        if announce_changes(db, event):
            promoted = next(
                player
                for player in run.snapshot["players"]
                if player["id"] == player_id
            )
            name = (
                clean(promoted["name"])
                if player_id.startswith("test-")
                else f"<@{player_id}>"
            )
            channel_id = event.channel_id or db.scalar(
                select(Announcement.channel_id)
                .where(Announcement.event_id == event_id)
                .order_by(Announcement.part)
                .limit(1)
            )
            if channel_id:
                part = db.scalar(
                    select(func.max(Announcement.part)).where(
                        Announcement.event_id == event_id
                    )
                )
                db.add(
                    Announcement(
                        id=str(uuid.uuid4()),
                        event_id=event_id,
                        part=(part if part is not None else -1) + 1,
                        kind="promotion",
                        channel_id=channel_id,
                        payload={
                            "content": (
                                f"{name} has been promoted from the waitlist "
                                f"to **{clean(table_name)}**."
                            ),
                            "allowed_mentions": {
                                "parse": [],
                                "users": (
                                    [] if player_id.startswith("test-") else [player_id]
                                ),
                            },
                            "nonce": hashlib.sha256(
                                f"{event_id}:manager-add:{player_id}".encode()
                            ).hexdigest()[:24],
                            "enforce_nonce": True,
                        },
                        created_at=time.time(),
                        next_attempt=time.time(),
                    )
                )
        enqueue_refresh(db, event)
        db.commit()
        return True
