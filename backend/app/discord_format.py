"""Shared formatting for Discord message content and embeds."""

import re
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
