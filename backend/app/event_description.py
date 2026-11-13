"""Description text used in Discord signup messages."""

from typing import Any

from app.discord_format import clean, event_embed, table_field
from app.models import Event

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
