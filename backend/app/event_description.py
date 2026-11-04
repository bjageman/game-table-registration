"""Description text used in Discord signup messages."""

from app.announcements import clean

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
