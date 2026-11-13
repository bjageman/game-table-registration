"""Public signup presentation shared by publication and roster refreshes."""

from typing import Any

from app.discord_format import clean
from app.event_description import (
    CUSTOM_DESCRIPTION,
    POLL_DESCRIPTION,
    REACTION_DESCRIPTION,
    signup_content,
    signup_description,
    signup_embed,
    signup_location,
)
from app.models import Event

EMOJIS = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟")


def signup_body(
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
