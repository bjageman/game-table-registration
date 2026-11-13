"""Refresh optional public signup rosters without changing votes or placements."""

import hashlib
import json
import logging
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy import Engine, case, exists, literal, or_, select, update
from sqlalchemy.orm import Session

from app.assignment_preferences import for_event
from app.discord_api import DiscordAPI, DiscordRequestError
from app.discord_format import clean
from app.event_description import (
    CUSTOM_DESCRIPTION,
    POLL_DESCRIPTION,
    REACTION_DESCRIPTION,
    signup_content,
    signup_description,
    signup_embed,
)
from app.models import AssignmentPreference, Event
from app.reactions import EMOJIS
from app.signups import apply_manager_signups, table_rows
from app.test_signups import add_to_rows

INTERVAL = 30
MAX_EDITS_PER_PASS = 10
logger = logging.getLogger(__name__)


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def base_embed(event: Event) -> dict[str, Any]:
    if event.signup_mode == "poll":
        return signup_embed(
            event, POLL_DESCRIPTION, f"Signups open for {event.duration_hours} hours."
        )
    deadline = (
        f"Signups close: <t:{int(event.closes_at)}:F> (<t:{int(event.closes_at)}:R>)"
        if event.closes_at is not None
        else "Signups stay open until closed manually."
    )
    labels = [
        f"{EMOJIS[index]} {clean(table['name'])}"
        if event.signup_mode == "reactions"
        else clean(table["name"])
        for index, table in enumerate(event.tables)
    ]
    return signup_embed(
        event,
        REACTION_DESCRIPTION
        if event.signup_mode == "reactions"
        else CUSTOM_DESCRIPTION,
        deadline,
        labels,
    )


def base_content(event: Event) -> str:
    if event.signup_mode == "poll":
        location = f"Location: {clean(event.location)}\n" if event.location else ""
        return (
            f"**{'[TEST] ' if event.test_signups else ''}{event.title}**\n"
            f"Event: <t:{int(event.starts_at)}:F>\n"
            f"{location}"
            f"Signups open for {event.duration_hours} hours. "
            f"{signup_description(event.description, POLL_DESCRIPTION)}"
        )
    deadline = (
        f"Signups close: <t:{int(event.closes_at)}:F> (<t:{int(event.closes_at)}:R>)"
        if event.closes_at is not None
        else "Signups stay open until closed manually."
    )
    reaction = event.signup_mode == "reactions"
    rows = [
        (
            f"{EMOJIS[index]} {clean(table['name'])} · {table['capacity']} seats"
            if reaction
            else f"- {clean(table['name'])} · {table['capacity']} seats"
        )
        for index, table in enumerate(event.tables)
    ]
    return signup_content(
        event,
        REACTION_DESCRIPTION if reaction else CUSTOM_DESCRIPTION,
        deadline,
        rows,
    )


def roster_pages(
    event: Event, base: dict[str, Any], rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_table = {
        row["name"]: {str(player["id"]): player for player in row["players"]}
        for row in rows
    }
    unique = {
        player_id
        for table in event.tables
        for player_id in by_table.get(table["name"], {})
    }
    first = {
        **base,
        "description": base["description"]
        + f"\n\n**Total users signed up: {len(unique)}**",
        "fields": [],
    }
    pages = [first]
    fields: list[dict[str, Any]] = []
    labels = [field["name"] for field in base.get("fields", [])]
    for index, table in enumerate(event.tables):
        players = by_table.get(table["name"], {})
        label = labels[index] if labels else clean(table["name"])
        heading = f"{label} ({len(players)}/{table['capacity']})"
        lines = [
            clean(players[pid]["name"]) if pid.startswith("test-") else f"<@{pid}>"
            for pid in sorted(players)
        ]
        chunks: list[str] = []
        current: list[str] = []
        for line in lines or ["No players signed up yet."]:
            if current and len("\n".join([*current, line])) > 1022:
                chunks.append("\n".join(current) + "\n\u200b")
                current = []
            current.append(line)
        if current:
            chunks.append("\n".join(current) + "\n\u200b")
        fields.extend(
            {
                "name": heading if part == 0 else f"{heading} (continued)",
                "value": value,
                "inline": True,
            }
            for part, value in enumerate(chunks)
        )
    for field in fields:
        page = pages[-1]
        length = (
            len(page["title"])
            + len(page["description"])
            + sum(len(item["name"]) + len(item["value"]) for item in page["fields"])
        )
        if page["fields"] and (
            len(page["fields"]) >= 25
            or length + len(field["name"]) + len(field["value"]) > 5800
        ):
            page = {
                "title": f"{base['title']} — Signups continued ({len(pages) + 1})",
                "description": f"[Signup post](https://discord.com/channels/{event.guild_id}/{event.channel_id}/{event.message_id})",
                "color": base["color"],
                "fields": [],
            }
            pages.append(page)
        page["fields"].append(field)
    return pages


def with_initial_roster(
    db: Session, event: Event, payload: dict[str, Any]
) -> dict[str, Any]:
    saved = for_event(db, event)
    if not saved or not saved.show_open_signup_players:
        return payload
    event.signup_roster_hash = "pending"
    event.signup_roster_checked_at = None
    rows = apply_manager_signups(
        db, event, add_to_rows(table_rows(db, event), event.test_signups)
    )
    return {**payload, "embeds": [roster_pages(event, payload["embeds"][0], rows)[0]]}


def _delete(discord: DiscordAPI, channel: str, message: str) -> None:
    try:
        discord.bot("DELETE", f"/channels/{channel}/messages/{message}", timeout=8)
    except DiscordRequestError as error:
        if error.discord_status != 404:
            raise


def _refresh(engine: Engine, discord: DiscordAPI, event_id: str) -> None:
    raw: list[dict[str, Any]] | None = None
    with Session(engine) as db:
        event = db.get(Event, event_id)
        if event is None:
            return
        saved = for_event(db, event)
        enabled = bool(saved and saved.show_open_signup_players)
        active = event.status == "open" and (
            event.closes_at is None or event.closes_at > time.time()
        )
        if (
            enabled
            and active
            and event.signup_mode == "reactions"
            and (event.reaction_error or event.reaction_checkpoint is None)
        ):
            return
        if enabled and active and event.signup_mode == "poll":
            assert event.message_id is not None
            raw = discord.table_signups(event.message_id, event.tables)
    with Session(engine) as db:
        claimed = db.execute(
            update(Event)
            .where(Event.id == event_id)
            .values(status=Event.status)
            .returning(Event.id)
        ).scalar_one_or_none()
        if claimed is None:
            return
        event = db.get(Event, event_id)
        assert event is not None
        if not event.message_id or not event.channel_id:
            return
        saved = for_event(db, event)
        active = (
            event.status == "open"
            and event.signup_deleted_at is None
            and (event.closes_at is None or event.closes_at > time.time())
        )
        enabled = bool(saved and saved.show_open_signup_players and active)
        cache = list(event.signup_roster_messages or [])
        try:
            if not active:
                for _ in range(min(MAX_EDITS_PER_PASS, max(0, len(cache) - 1))):
                    _delete(discord, event.channel_id, cache[-1]["id"])
                    cache.pop()
                    event.signup_roster_messages = list(cache)
                event.signup_roster_hash = "pending" if len(cache) > 1 else None
                event.signup_roster_messages = cache if len(cache) > 1 else None
                db.commit()
                return
            base = base_embed(event)
            if enabled:
                rows = apply_manager_signups(
                    db,
                    event,
                    add_to_rows(
                        raw if raw is not None else table_rows(db, event),
                        event.test_signups,
                    ),
                )
                parts: list[dict[str, Any]] = [
                    {"embeds": [page]} for page in roster_pages(event, base, rows)
                ]
            elif event.signup_roster_hash is not None:
                parts = [{"content": base_content(event), "embeds": []}]
            else:
                parts = []
            wanted = digest(parts)
            if enabled and event.signup_roster_hash == wanted:
                return
            if not parts:
                return
            event.signup_roster_hash = "pending"
            edits = 0
            complete = True
            for part, part_payload in enumerate(parts):
                part_hash = digest(part_payload)
                existing = cache[part] if len(cache) > part else None
                if existing and existing["digest"] == part_hash:
                    continue
                if edits >= MAX_EDITS_PER_PASS:
                    complete = False
                    break
                edits += 1
                payload: dict[str, Any] = {
                    **part_payload,
                    "allowed_mentions": {"parse": [], "users": []},
                }
                message_id = (
                    event.message_id
                    if part == 0
                    else existing["id"]
                    if existing
                    else None
                )
                if message_id:
                    try:
                        discord.edit_announcement(event.channel_id, message_id, payload)
                    except DiscordRequestError as error:
                        if part == 0 or error.discord_status != 404:
                            raise
                        message_id = None
                if message_id is None:
                    payload.update(
                        content=f"Signup roster for {event.title} (part {part + 1})\nhttps://discord.com/channels/{event.guild_id}/{event.channel_id}/{event.message_id}",
                        nonce=digest([event.id, part, part_hash])[:24],
                        enforce_nonce=True,
                        message_reference={
                            "message_id": event.message_id,
                            "fail_if_not_exists": False,
                        },
                    )
                    message_id = discord.find_announcement(
                        event.channel_id, payload, event.published_at or 0
                    )
                    if message_id:
                        discord.edit_announcement(
                            event.channel_id,
                            message_id,
                            {
                                **part_payload,
                                "allowed_mentions": {"parse": [], "users": []},
                            },
                        )
                    else:
                        message_id = str(
                            discord.send_announcement(event.channel_id, payload)["id"]
                        )
                item = {"id": message_id, "digest": part_hash}
                if len(cache) > part:
                    cache[part] = item
                else:
                    cache.append(item)
                event.signup_roster_messages = list(cache)
            if complete:
                while len(cache) > len(parts):
                    if edits >= MAX_EDITS_PER_PASS:
                        complete = False
                        break
                    _delete(discord, event.channel_id, cache[-1]["id"])
                    edits += 1
                    cache.pop()
                    event.signup_roster_messages = list(cache)
            if complete:
                event.signup_roster_hash = wanted if enabled else None
                event.signup_roster_messages = cache if enabled else None
            db.commit()
        except Exception:
            db.commit()
            raise


def synchronize_due(
    engine: Engine, client_for: Callable[[str, str], DiscordAPI]
) -> None:
    now = time.time()
    scope = case(
        (Event.organization_id.is_not(None), literal("org:") + Event.organization_id),
        else_=literal("user:") + Event.created_by,
    )
    enabled = exists(
        select(AssignmentPreference.scope_key).where(
            AssignmentPreference.scope_key == scope,
            AssignmentPreference.show_open_signup_players.is_(True),
        )
    )
    with Session(engine) as db:
        due = list(
            db.execute(
                select(Event.id, Event.guild_id, Event.channel_id)
                .where(
                    Event.message_id.is_not(None),
                    Event.channel_id.is_not(None),
                    or_(
                        Event.signup_roster_hash.is_not(None),
                        (Event.status == "open") & enabled,
                    ),
                    or_(
                        Event.signup_roster_checked_at.is_(None),
                        Event.signup_roster_checked_at <= now - INTERVAL,
                    ),
                )
                .order_by(Event.signup_roster_checked_at.asc(), Event.id)
                .limit(50)
            )
        )
    for event_id, guild, channel in due:
        assert channel is not None
        with Session(engine) as db:
            claimed = db.execute(
                update(Event)
                .where(
                    Event.id == event_id,
                    or_(
                        Event.signup_roster_checked_at.is_(None),
                        Event.signup_roster_checked_at <= now - INTERVAL,
                    ),
                )
                .values(signup_roster_checked_at=now)
                .returning(Event.id)
            ).scalar_one_or_none()
            db.commit()
        if claimed is None:
            continue
        try:
            _refresh(engine, client_for(guild, channel), event_id)
        except Exception:
            logger.exception("Could not refresh open signup roster for %s", event_id)
