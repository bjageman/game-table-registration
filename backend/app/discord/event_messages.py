"""Build signup/assignment messages and queue their durable delivery records."""

import hashlib
import time
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.discord.discord_format import (
    TABLE_FIELD_CONTENT_LIMIT,
    clean,
    event_embed,
    is_discord_user_id,
    paginate_fields,
    player_reference,
    table_field,
)
from app.models import Announcement, Event

REACTION_DESCRIPTION = (
    "React with the number for every table you would attend. "
    "Remove your reaction to withdraw from that table. "
    "This is a lottery entry, not a guaranteed seat. "
    "Only reactions received before signups close count."
)
CUSTOM_DESCRIPTION = (
    "Choose every specific table you would attend. "
    "This is a lottery entry, not a guaranteed seat. "
    "View, change, or withdraw your choices below, directly in Discord."
)
POLL_DESCRIPTION = (
    "Select every table you would attend. "
    "This is a lottery entry, not a guaranteed seat."
)


def signup_description(value: str | None, default: str) -> str:
    description = value.strip() if value else ""
    if not description:
        return default
    return "\n".join(clean(line) for line in description.splitlines())


def signup_location(value: str | None) -> str:
    return f"Location: {clean(value)}\n" if value and value.strip() else ""


def signup_content(
    event: Event,
    default: str,
    deadline: str,
    tables: list[str] | None = None,
) -> str:
    message = (
        f"**{'[TEST] ' if event.test_signups else ''}{clean(event.title)}**\n"
        f"Event: <t:{int(event.starts_at)}:F>\n"
        f"{signup_location(event.location)}{deadline}"
    )
    if tables:
        message += "\n\n" + "\n".join(tables)
    return f"{message}\n\n{signup_description(event.description, default)}"


def signup_embed(
    event: Event, default: str, deadline: str, labels: list[str] | None = None
) -> dict[str, Any]:
    details = [f"Event: <t:{int(event.starts_at)}:F>"]
    location = signup_location(event.location).rstrip()
    if location:
        details.append(location)
    details.append(deadline)
    fields = (
        [
            table_field(label, f"{table['capacity']} seats")
            for label, table in zip(labels, event.tables, strict=True)
        ]
        if labels is not None
        else None
    )
    return event_embed(
        event, signup_description(event.description, default), details, fields
    )


EMOJIS = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟")


def build_signup_message(
    event: Event,
    mode: str,
    closes_at: float | None,
    include_roster: bool,
) -> dict[str, Any]:
    default = {
        "poll": POLL_DESCRIPTION,
        "reactions": REACTION_DESCRIPTION,
        "custom": CUSTOM_DESCRIPTION,
    }[mode]
    deadline = (
        f"Signups open for {event.duration_hours} hours."
        if mode == "poll"
        else f"Signups close: <t:{int(closes_at)}:F> (<t:{int(closes_at)}:R>)"
        if closes_at is not None
        else "Signups stay open until closed manually."
    )
    labels = [
        f"{EMOJIS[index]} {clean(table['name'])}"
        if mode == "reactions"
        else clean(table["name"])
        for index, table in enumerate(event.tables)
    ]
    if include_roster:
        return {
            "embeds": [
                signup_embed(
                    event, default, deadline, None if mode == "poll" else labels
                )
            ]
        }
    if mode == "poll":
        return {
            "content": (
                f"**{'[TEST] ' if event.test_signups else ''}{event.title}**\n"
                f"Event: <t:{int(event.starts_at)}:F>\n"
                f"{signup_location(event.location)}{deadline} "
                f"{signup_description(event.description, default)}"
            )
        }
    rows = [
        f"{label if mode == 'reactions' else '- ' + label} · {table['capacity']} seats"
        for label, table in zip(labels, event.tables, strict=True)
    ]
    return {"content": signup_content(event, default, deadline, rows)}


def build_assignment_messages(
    event: Event,
    channel_id: str,
    result: dict[str, Any],
    snapshot: dict[str, Any],
    notify: bool = True,
) -> list[dict[str, Any]]:
    is_test = bool(snapshot.get("is_test"))

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
        table_entries = [
            (
                player_reference(p),
                p["id"] if not is_test and is_discord_user_id(p["id"]) else None,
            )
            for p in table["players"]
        ]
        if not table_entries:
            table_entries.append(("No players assigned.", None))
        for index, player in enumerate(table.get("waitlist", []), 1):
            line = f"{index}. {player_reference(player)}"
            if index == 1:
                line = f"\n⌛ Waitlist\n{line}"
            table_entries.append((line, None))
        sections.append((header, table_entries, True))
    poll_url = (
        f"https://discord.com/channels/{event.guild_id}/{channel_id}/{event.message_id}"
    )
    details = [f"Event: <t:{int(event.starts_at)}:F>"] if event.starts_at else []
    location = signup_location(event.location).rstrip()
    if location:
        details.append(location)
    details.append(f"[Signup message]({poll_url})")
    introduction = signup_description(event.description, "Table assignments are ready.")
    max_ping_length = 1500
    field_parts: list[tuple[dict[str, Any], list[str]]] = []
    for header, entries, spaced in sections:
        lines: list[str] = []
        ids: list[str] = []
        part = 0
        for line, mention in entries:
            field_full = len("\n".join(lines)) + len(line) + 1 > (
                TABLE_FIELD_CONTENT_LIMIT if spaced else 1024
            )
            mentions_full = bool(
                notify
                and mention
                and (
                    len(ids) >= 100
                    or sum(len(user_id) + 4 for user_id in ids) + len(mention) + 4
                    > max_ping_length
                )
            )
            if lines and (field_full or mentions_full):
                field_parts.append(
                    (
                        {
                            **table_field(
                                header if part == 0 else f"{header} (continued)",
                                "\n".join(lines),
                                spaced,
                            ),
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
                    **table_field(
                        header if part == 0 else f"{header} (continued)",
                        "\n".join(lines),
                        spaced,
                    ),
                },
                ids,
            )
        )

    def make_embed(page: int) -> dict[str, Any]:
        page_details = list(details)
        if page:
            page_details.append(f"Assignments continued ({page + 1})")
        return event_embed(event, introduction, page_details, is_test=is_test)

    chunks = paginate_fields(field_parts, make_embed, notify=notify)
    payloads: list[dict[str, Any]] = []
    for i, (embed, mentions) in enumerate(chunks):
        payloads.append(
            {
                "content": (
                    " ".join(f"<@{user_id}>" for user_id in mentions)
                    if notify and mentions
                    else ""
                ),
                "embeds": [embed],
                "allowed_mentions": {
                    "parse": [],
                    "users": mentions if notify else [],
                },
                "nonce": hashlib.sha256(
                    f"{event.id}:assignments:{i}".encode()
                ).hexdigest()[:24],
                "enforce_nonce": True,
            }
        )
    return payloads


def enqueue_assignment_messages(
    db: Session,
    event: Event,
    channel_id: str,
    result: dict[str, Any],
    snapshot: dict[str, Any],
) -> None:
    now = time.time()
    for part, payload in enumerate(
        build_assignment_messages(event, channel_id, result, snapshot)
    ):
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
    enqueue_withdrawal_instructions(db, event, channel_id, now)


def enqueue_roster_refresh(db: Session, event: Event) -> None:
    """Queue one edit of the existing assignment posts after a placement change."""
    assignment = db.scalar(
        select(Announcement)
        .where(Announcement.event_id == event.id, Announcement.kind == "assignment")
        .order_by(Announcement.part)
        .limit(1)
    )
    if assignment is None or db.scalar(
        select(Announcement.id)
        .where(
            Announcement.event_id == event.id,
            Announcement.kind == "refresh",
            Announcement.state == "pending",
        )
        .limit(1)
    ):
        return
    part = db.scalar(
        select(func.max(Announcement.part)).where(Announcement.event_id == event.id)
    )
    now = time.time()
    db.add(
        Announcement(
            id=str(uuid.uuid4()),
            event_id=event.id,
            part=(part if part is not None else -1) + 1,
            kind="refresh",
            channel_id=assignment.channel_id,
            payload={"content": "Refresh assignment posts"},
            created_at=now,
            next_attempt=now,
        )
    )


def enqueue_withdrawal_instructions(
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
