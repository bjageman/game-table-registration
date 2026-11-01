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

    sections: list[tuple[str, list[tuple[str, str | None]]]] = []
    for table in result["tables"]:
        header = f"**{clean(table['name'])} — {len(table['players'])} assigned**"
        lines = [
            (f"- {name(p)}", p["id"] if not is_test else None) for p in table["players"]
        ]
        sections.append((header, lines or [("No players assigned.", None)]))
    by_id = {p["id"]: p for p in snapshot["players"]}
    waiting: list[tuple[str, str | None]] = []
    for i, pid in enumerate(result["waitlist"], 1):
        choices = ", ".join(clean(name) for name in by_id[pid]["choices"])
        waiting.append((f"{i}. {name(by_id[pid])} — {choices}", None))
    if waiting:
        sections.append(("**Waitlist**", waiting))
    chunks: list[tuple[str, list[str]]] = []
    content: list[str] = []
    mentions: list[str] = []

    def flush() -> None:
        if content:
            chunks.append(("\n".join(content), list(mentions)))
            content.clear()
            mentions.clear()

    for header, entries in sections:
        if (
            sum(len(s) + 1 for s in content) + len(header) + len(entries[0][0]) + 2
            > 1400
        ):
            flush()
        content.append(header)
        for line, mention in entries:
            if (
                sum(len(s) + 1 for s in content) + len(line) + 1 > 1400
                or mention
                and len(mentions) >= 100
            ):
                flush()
                content.append(header + " (continued)")
            content.append(line)
            if mention:
                mentions.append(mention)
        content.append("")
    flush()
    poll_url = (
        f"https://discord.com/channels/{event.guild_id}/{channel_id}/{event.message_id}"
    )
    return [
        {
            "content": (
                f"**{'[TEST] ' if is_test else ''}{clean(event.title)} "
                "— Table Assignments "
                f"({i + 1}/{len(chunks)})**\n[Signup poll]({poll_url})\n\n{body}"
            ),
            "allowed_mentions": {"parse": [], "users": mentions},
            "nonce": hashlib.sha256(f"{event.id}:assignments:{i}".encode()).hexdigest()[
                :24
            ],
            "enforce_nonce": True,
        }
        for i, (body, mentions) in enumerate(chunks)
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


def deliver_event(
    engine: Engine, discord: DiscordAPI, event_id: str, limit: int = 1
) -> None:
    for _ in range(limit):
        token = secrets.token_hex(16)
        now = time.time()
        with Session(engine) as db:
            row = db.scalar(
                select(Announcement)
                .where(Announcement.event_id == event_id, Announcement.state != "sent")
                .order_by(Announcement.part)
                .limit(1)
            )
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
            with Session(engine) as db:
                db.execute(
                    update(Announcement)
                    .where(Announcement.id == row_id, Announcement.token == token)
                    .values(
                        state="sent",
                        message_id=message_id,
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
            .where(Announcement.state != "sent")
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
                .where(Announcement.event_id == event_id)
                .order_by(Announcement.part)
            )
        )
        if not rows:
            return {"status": "unavailable", "error": None, "url": None}
        state = (
            "sent"
            if all(row.state == "sent" for row in rows)
            else "needs_review"
            if any(row.state == "needs_review" for row in rows)
            else "pending"
        )
        first = next((row for row in rows if row.message_id), None)
        return {
            "status": state,
            "error": next((row.error for row in rows if row.error), None),
            "url": f"https://discord.com/channels/{guild_id}/{first.channel_id}/{first.message_id}"
            if first
            else None,
        }
