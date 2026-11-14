from types import SimpleNamespace

from app.discord.reactions import publication as reaction_publication
from app.events.event_description import REACTION_DESCRIPTION
from app.events.signups import publication as custom_publication


def event(description: str):
    return SimpleNamespace(
        id="event",
        title="Game Night",
        description=description,
        location="Game Store",
        test_signups=None,
        starts_at=2000000000,
        tables=[{"name": "Table A", "capacity": 8}],
    )


def test_reaction_message_uses_existing_instructions_for_blank_description():
    content = reaction_publication(event(""), 1999990000)["embeds"][0]["description"]
    assert REACTION_DESCRIPTION in content
    assert "Location: Game Store" in content


def test_custom_description_replaces_signup_instructions():
    for publication in (reaction_publication, custom_publication):
        content = publication(event("Bring friends\n@everyone"), 1999990000)["embeds"][
            0
        ]["description"]
        assert content.startswith("Bring friends\n@everyone\n\nEvent:")
        embed = publication(event("Bring friends"), 1999990000)["embeds"][0]
        assert embed["title"] == "Game Night"
        assert all(field["inline"] is True for field in embed["fields"])
        assert "This is a lottery entry" not in content
