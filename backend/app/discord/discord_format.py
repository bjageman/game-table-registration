"""Shared formatting for Discord message content and embeds."""

import re
from collections.abc import Callable
from typing import Any

from app.models import Event

EMBED_COLOR = 0x2F6B4F
# Discord has no field width setting. An invisible eight-em line gives short
# table columns a shared minimum footprint. Zero-width anchors prevent trimming.
TABLE_FIELD_SPACER = "\n\u200b" + "\u2002" * 16 + "\u200b"
TABLE_FIELD_CONTENT_LIMIT = 1024 - len(TABLE_FIELD_SPACER)


def clean(text: str) -> str:
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~\-])", r"\\\1", " ".join(text.split()))


def event_embed(
    event: Event,
    introduction: str,
    details: list[str],
    fields: list[dict[str, Any]] | None = None,
    is_test: bool | None = None,
) -> dict[str, Any]:
    test = bool(event.test_signups) if is_test is None else is_test
    embed: dict[str, Any] = {
        "title": f"{'[TEST] ' if test else ''}{clean(event.title)}",
        "description": f"{introduction}\n\n" + "\n".join(details),
        "color": EMBED_COLOR,
    }
    if fields is not None:
        embed["fields"] = fields
    return embed


def table_field(name: str, value: str, inline: bool = True) -> dict[str, Any]:
    if inline:
        value += TABLE_FIELD_SPACER
    return {"name": name, "value": value, "inline": inline}


FieldPart = tuple[dict[str, Any], list[str]]


def embed_length(embed: dict[str, Any]) -> int:
    """Count all text included in Discord's 6,000-character embed budget."""
    return (
        len(embed.get("title", ""))
        + len(embed.get("description", ""))
        + len(embed.get("author", {}).get("name", ""))
        + len(embed.get("footer", {}).get("text", ""))
        + sum(
            len(field["name"]) + len(field["value"])
            for field in embed.get("fields", [])
        )
    )


def split_field_lines(
    lines: list[str], limit: int = TABLE_FIELD_CONTENT_LIMIT
) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    for line in lines:
        if len(line) > limit:
            raise ValueError("A roster entry exceeds Discord's field limit")
        if current and len("\n".join([*current, line])) > limit:
            chunks.append("\n".join(current))
            current = []
        current.append(line)
    if current:
        chunks.append("\n".join(current))
    return chunks


def paginate_fields(
    parts: list[FieldPart],
    make_embed: Callable[[int], dict[str, Any]],
    notify: bool = False,
) -> list[tuple[dict[str, Any], list[str]]]:
    """Pack fields against full embed and optional notification budgets."""
    pages: list[tuple[dict[str, Any], list[str]]] = []
    embed = make_embed(0)
    embed["fields"] = []
    mentions: list[str] = []
    for field, ids in parts:
        combined = mentions + ids
        too_many_mentions = notify and (
            len(combined) > 100
            or len(" ".join(f"<@{user}>" for user in combined)) > 1500
        )
        if embed["fields"] and (
            len(embed["fields"]) >= 25
            or embed_length(embed) + len(field["name"]) + len(field["value"]) > 6000
            or too_many_mentions
        ):
            pages.append((embed, mentions))
            embed = make_embed(len(pages))
            embed["fields"] = []
            mentions = []
        embed["fields"].append(field)
        mentions.extend(ids)
        if (
            len(field["name"]) > 256
            or len(field["value"]) > 1024
            or embed_length(embed) > 6000
        ):
            raise ValueError("A roster field cannot fit in a Discord embed")
    if embed["fields"]:
        pages.append((embed, mentions))
    return pages
