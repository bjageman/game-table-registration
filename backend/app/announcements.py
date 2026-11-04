"""Durable assignment announcements; never rerun the lottery for delivery."""

import hashlib
import re
import secrets
import time
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import Engine, func, or_, select, update
from sqlalchemy.orm import Session

from app.discord_api import DiscordAPI, DiscordRequestError
from app.models import Announcement, Event


def clean(text: str) -> str:
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~\-])", r"\\\1", " ".join(text.split()))


def payloads(
    event: Event, channel_id: str, result: dict[str, Any], snapshot: dict[str, Any]
) -> list[dict[str, Any]]:
    is_test = bool(snapshot.get("is_test"))

    def name(player: dict[str, Any]) -> str:
        return (
            clean(player["name"])
            if player["id"].startswith("test-")
            else f"<@{player['id']}>"
        )

    sections: list[tuple[str, list[tuple[str, str | None]], bool]] = []
    capacities = {table["name"]: table["capacity"] for table in event.tables or []}
    for table in result["tables"]:
        capacity = capacities.get(table["name"])
        count = (
            f"{len(table['players'])}/{capacity}"
            if capacity is not None
            else str(len(table["players"]))
        )
        header = f"{clean(table['name'])} ({count})"
        lines = [(name(p), p["id"] if not is_test else None) for p in table["players"]]
        sections.append((header, lines or [("No players assigned.", None)], True))
    by_id = {p["id"]: p for p in snapshot["players"]}
    waiting: list[tuple[str, str | None]] = []
    for i, pid in enumerate(result["waitlist"], 1):
        waiting.append((f"{i}. {name(by_id[pid])}", None))
    if waiting:
        sections.append((f"Waitlist ({len(waiting)})", waiting, False))
    poll_url = (
        f"https://discord.com/channels/{event.guild_id}/{channel_id}/{event.message_id}"
    )
    introduction = (
        f"**{'[TEST] ' if is_test else ''}{clean(event.title)} — Table Assignments**"
        + (f"\nEvent: <t:{int(event.starts_at)}:F>" if event.starts_at else "")
        + (f"\nLocation: {clean(event.location)}" if event.location else "")
        + f"\n[Signup message]({poll_url})"
    )
    max_ping_length = min(1500, 1900 - len(introduction) - 1)
    field_parts: list[tuple[dict[str, Any], list[str]]] = []
    for header, entries, inline in sections:
        lines: list[str] = []
        ids: list[str] = []
        part = 0
        for line, mention in entries:
            if lines and (
                len("\n".join(lines)) + len(line) + 1 > 1024
                or mention
                and len(ids) >= 100
                or mention
                and sum(len(user_id) + 4 for user_id in ids) + len(mention) + 4
                > max_ping_length
            ):
                field_parts.append(
                    (
                        {
                            "name": header if part == 0 else f"{header} (continued)",
                            "value": "\n".join(lines),
                            "inline": inline,
                        },
                        ids,
                    )
                )
                part += 1
                lines, ids = [], []
            lines.append(line)
            if mention:
                ids.append(mention)
        field_parts.append(
            (
                {
                    "name": header if part == 0 else f"{header} (continued)",
                    "value": "\n".join(lines),
                    "inline": inline,
                },
                ids,
            )
        )

    chunks: list[tuple[list[dict[str, Any]], list[str]]] = []
    fields: list[dict[str, Any]] = []
    mentions: list[str] = []
    field_length = 0
    for field, ids in field_parts:
        next_length = len(field["name"]) + len(field["value"])
        intro = introduction if not chunks else "Assignments continued (999)"
        ping_length = sum(len(user_id) + 4 for user_id in mentions + ids)
        if fields and (
            len(fields) >= 25
            or field_length + next_length > 5800
            or len(mentions) + len(ids) > 100
            or len(intro) + ping_length > 1900
        ):
            chunks.append((fields, mentions))
            fields, mentions, field_length = [], [], 0
        fields.append(field)
        mentions.extend(ids)
        field_length += next_length
    if fields:
        chunks.append((fields, mentions))
    return [
        {
            "content": (introduction if i == 0 else f"Assignments continued ({i + 1})")
            + (
                "\n" + " ".join(f"<@{user_id}>" for user_id in mentions)
                if mentions
                else ""
            ),
            "embeds": [{"color": 0x2F6B4F, "fields": fields}],
            "allowed_mentions": {"parse": [], "users": mentions},
            "nonce": hashlib.sha256(f"{event.id}:assignments:{i}".encode()).hexdigest()[
                :24
            ],
            "enforce_nonce": True,
        }
        for i, (fields, mentions) in enumerate(chunks)
    ]


def enqueue(
    db: Session,
    event: Event,
    channel_id: str,
    result: dict[str, Any],
    snapshot: dict[str, Any],
) -> None:
    now = time.time()
    for part, payload in enumerate(payloads(event, channel_id, result, snapshot)):
        db.add(
            Announcement(
                id=str(uuid.uuid4()),
                event_id=event.id,
                part=part,
                channel_id=channel_id,
                payload=payload,
                created_at=now,
                next_attempt=now,
            )
        )
    enqueue_instructions(db, event, channel_id, now)


def enqueue_instructions(
    db: Session, event: Event, channel_id: str, now: float | None = None
) -> None:
    if db.scalar(
        select(Announcement.id).where(
            Announcement.event_id == event.id,
            Announcement.kind == "instructions",
        )
    ):
        return
    now = now or time.time()
    part = db.scalar(
        select(func.max(Announcement.part)).where(Announcement.event_id == event.id)
    )
    db.add(
        Announcement(
            id=str(uuid.uuid4()),
            event_id=event.id,
            part=(part if part is not None else -1) + 1,
            kind="instructions",
            channel_id=channel_id,
            payload={
                "content": "If you need to cancel, please react ❌ to withdraw from "
                "your table and free up a space for a waitlisted player.",
                "allowed_mentions": {"parse": [], "users": []},
                "nonce": hashlib.sha256(
                    f"{event.id}:withdrawal-instructions".encode()
                ).hexdigest()[:24],
                "enforce_nonce": True,
            },
            created_at=now,
            next_attempt=now,
        )
    )


def deliver_event(
    engine: Engine, discord: DiscordAPI, event_id: str, limit: int = 1
) -> None:
    for _ in range(limit):
        token = secrets.token_hex(16)
        now = time.time()
        with Session(engine) as db:
            row = db.scalar(
                select(Announcement)
                .where(
                    Announcement.event_id == event_id,
                    Announcement.state.in_(["pending", "sending"]),
                )
                .order_by(Announcement.part)
                .limit(1)
            )
            event = db.get(Event, event_id)
            if (
                row is not None
                and row.kind in ("promotion", "instructions")
                and event
                and event.archived_at
            ):
                if row.unknown or row.state == "sending" or row.message_id:
                    return
                row.state = "sent"
                row.deleted_at = now
                row.token = None
                row.lease_until = None
                db.commit()
                continue
            if row is None or row.state == "needs_review" or row.next_attempt > now:
                return
            recovering = row.state == "sending"
            unknown = row.unknown or recovering
            attempted_at = row.attempted_at or now
            changed = db.execute(
                update(Announcement)
                .where(
                    Announcement.id == row.id,
                    Announcement.state.in_(["pending", "sending"]),
                    or_(Announcement.token.is_(None), Announcement.lease_until <= now),
                )
                .values(
                    state="sending",
                    token=token,
                    lease_until=now + 90,
                    attempts=Announcement.attempts + 1,
                    attempted_at=now,
                )
                .returning(Announcement.id)
            ).scalar_one_or_none()
            db.commit()
            if not changed:
                return
            db.refresh(row)
            row_id, channel_id, payload, attempts = (
                row.id,
                row.channel_id,
                row.payload,
                row.attempts,
            )
            row_kind = row.kind
        try:
            if unknown:
                message_id = discord.find_announcement(
                    channel_id, payload, attempted_at
                )
                if message_id is None:
                    raise RuntimeError(
                        "Delivery could not be confirmed. "
                        "Check Discord before retrying."
                    )
            else:
                message_id = str(discord.send_announcement(channel_id, payload)["id"])
            if row_kind == "instructions":
                discord.seed_reactions(message_id, ["❌"])
            deleted_at = None
            if row_kind == "promotion":
                with Session(engine) as db:
                    event = db.get(Event, event_id)
                    archived = bool(event and event.archived_at)
                if archived:
                    try:
                        discord.delete_poll(message_id)
                        deleted_at = time.time()
                    except Exception:
                        # Keep the message ID so archived-event cleanup can retry.
                        pass
            with Session(engine) as db:
                db.execute(
                    update(Announcement)
                    .where(Announcement.id == row_id, Announcement.token == token)
                    .values(
                        state="sent",
                        message_id=message_id,
                        deleted_at=deleted_at,
                        token=None,
                        lease_until=None,
                        error=None,
                        unknown=False,
                    )
                )
                db.commit()
        except Exception as failure:
            uncertain = (
                unknown
                or not isinstance(failure, DiscordRequestError)
                or failure.ambiguous
            )
            # A transport timeout may have happened after Discord accepted the send.
            # Reconcile on the next pass, never blindly repost an ambiguous result.
            state = "needs_review" if unknown else "pending"
            if (
                isinstance(failure, DiscordRequestError)
                and failure.discord_status == 400
            ):
                state = "needs_review"
            error = (
                "Delivery could not be confirmed. Check Discord before retrying."
                if uncertain
                else "Discord could not accept the announcement. "
                "Automatic retry is queued."
            )
            retry_after = (
                failure.retry_after if isinstance(failure, DiscordRequestError) else 0
            )
            with Session(engine) as db:
                db.execute(
                    update(Announcement)
                    .where(Announcement.id == row_id, Announcement.token == token)
                    .values(
                        state=state,
                        error=error,
                        unknown=uncertain,
                        token=None,
                        lease_until=None,
                        next_attempt=time.time()
                        + max(retry_after, min(3600, 5 * 2 ** min(attempts, 10))),
                    )
                )
                db.commit()
            return


def dispatch_due(engine: Engine, client_for: Callable[[str, str], DiscordAPI]) -> None:
    with Session(engine) as db:
        first = (
            select(Announcement.event_id, func.min(Announcement.part).label("part"))
            .where(Announcement.state.in_(["pending", "sending"]))
            .group_by(Announcement.event_id)
            .subquery()
        )
        rows = list(
            db.execute(
                select(Announcement.event_id, Event.guild_id, Announcement.channel_id)
                .join(Event, Event.id == Announcement.event_id)
                .join(
                    first,
                    (first.c.event_id == Announcement.event_id)
                    & (first.c.part == Announcement.part),
                )
                .where(
                    or_(
                        Announcement.kind != "promotion",
                        Event.archived_at.is_(None),
                    ),
                    Announcement.state.in_(["pending", "sending"]),
                    Announcement.next_attempt <= time.time(),
                    or_(
                        Announcement.token.is_(None),
                        Announcement.lease_until <= time.time(),
                    ),
                )
                .order_by(Announcement.next_attempt)
                .limit(20)
            )
        )
    for event_id, guild_id, channel_id in rows:
        deliver_event(engine, client_for(guild_id, channel_id), event_id, limit=5)


def status(engine: Engine, event_id: str, guild_id: str) -> dict[str, Any]:
    with Session(engine) as db:
        rows = list(
            db.scalars(
                select(Announcement)
                .where(
                    Announcement.event_id == event_id,
                    Announcement.kind.in_(["assignment", "instructions"]),
                )
                .order_by(Announcement.part)
            )
        )
        if not rows:
            return {"status": "unavailable", "error": None, "url": None}
        state = (
            "deleted"
            if all(row.deleted_at for row in rows)
            else "sent"
            if all(row.state == "sent" for row in rows)
            else "needs_review"
            if any(row.state == "needs_review" for row in rows)
            else "pending"
        )
        first = next(
            (row for row in rows if row.message_id and not row.deleted_at), None
        )
        return {
            "status": state,
            "error": next((row.error for row in rows if row.error), None),
            "url": f"https://discord.com/channels/{guild_id}/{first.channel_id}/{first.message_id}"
            if first
            else None,
        }
