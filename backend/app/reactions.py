"""Persist numbered reaction selections and track recoverable Gateway gaps."""

import time
from typing import Any

from sqlalchemy import Engine, delete, select, update
from sqlalchemy.orm import Session

from app.announcements import clean
from app.models import Event, TableSignup

EMOJIS = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟")
GAP = (
    "Reaction signups need synchronization. Keep the bot connected before the deadline."
)


def publication(event: Event, closes_at: float) -> dict[str, Any]:
    tables = "\n".join(
        f"{EMOJIS[i]} {clean(t['name'])} · {t['capacity']} seats"
        for i, t in enumerate(event.tables)
    )
    return {
        "content": (
            f"**{'[TEST] ' if event.test_signups else ''}{clean(event.title)}**\n"
            f"Event: <t:{int(event.starts_at)}:F>\n"
            f"Signups close: <t:{int(closes_at)}:F> (<t:{int(closes_at)}:R>)\n\n"
            f"{tables}\n\n"
            "React with the number for every table you would attend. "
            "Remove your reaction to withdraw from that table. "
            "This is a lottery entry, not a guaranteed seat. "
            "Only reactions received before signups close count."
        ),
        "allowed_mentions": {"parse": []},
    }


def event_for(engine: Engine, guild: str, channel: str, message: str) -> str | None:
    with Session(engine) as db:
        return db.scalar(
            select(Event.id).where(
                Event.guild_id == guild,
                Event.channel_id == channel,
                Event.message_id == message,
                Event.signup_mode == "reactions",
                Event.status == "open",
            )
        )


def change(
    engine: Engine,
    event_id: str,
    emoji: str | None,
    user_id: str | None,
    name: str,
    added: bool,
    observed_at: float,
) -> None:
    with Session(engine) as db:
        claimed = db.execute(
            update(Event)
            .where(
                Event.id == event_id,
                Event.status == "open",
                Event.signup_mode == "reactions",
                Event.closes_at > observed_at,
            )
            .values(status=Event.status)
            .returning(Event.id)
        ).scalar_one_or_none()
        if claimed is None:
            return
        event = db.get(Event, event_id)
        assert event is not None
        if emoji is not None and emoji not in EMOJIS[: len(event.tables)]:
            return
        table = event.tables[EMOJIS.index(emoji)]["name"] if emoji else None
        if user_id is None:
            rows = list(
                db.scalars(select(TableSignup).where(TableSignup.event_id == event_id))
            )
        else:
            row = db.get(TableSignup, (event_id, user_id))
            rows = [row] if row else []
            if added and not row:
                row = TableSignup(
                    event_id=event_id,
                    discord_id=user_id,
                    discord_name=name[:100],
                    choices=[],
                )
                db.add(row)
                rows = [row]
        for row in rows:
            choices = set(row.choices)
            if added and table:
                choices.add(table)
                row.discord_name = name[:100]
            elif table:
                choices.discard(table)
            else:
                choices.clear()
            row.choices = [t["name"] for t in event.tables if t["name"] in choices]
            if not row.choices:
                db.delete(row)
        db.commit()


def mark_gap(engine: Engine) -> None:
    with Session(engine) as db:
        db.execute(
            update(Event)
            .where(
                Event.signup_mode == "reactions",
                Event.status == "open",
                (Event.reaction_checkpoint.is_(None))
                | (Event.reaction_checkpoint < Event.closes_at),
            )
            .values(reaction_error=GAP)
        )
        db.commit()


def pending(engine: Engine) -> list[dict[str, Any]]:
    with Session(engine) as db:
        return [
            {
                "id": e.id,
                "guild": e.guild_id,
                "channel": e.channel_id,
                "message": e.message_id,
                "tables": e.tables,
                "deadline": e.closes_at,
                "sync": e.reaction_checkpoint is None or bool(e.reaction_error),
            }
            for e in db.scalars(
                select(Event).where(
                    Event.signup_mode == "reactions",
                    Event.status == "open",
                    (Event.reaction_checkpoint.is_(None))
                    | (Event.reaction_checkpoint < Event.closes_at),
                )
            )
        ]


def replace(
    engine: Engine, event_id: str, participants: list[dict[str, Any]], started: float
) -> bool:
    with Session(engine) as db:
        changed = db.execute(
            update(Event)
            .where(
                Event.id == event_id,
                Event.status == "open",
                Event.closes_at > time.time(),
                Event.signup_mode == "reactions",
            )
            .values(reaction_checkpoint=started, reaction_error=None)
            .returning(Event.id)
        ).scalar_one_or_none()
        if not changed:
            return False
        db.execute(delete(TableSignup).where(TableSignup.event_id == event_id))
        for player in participants:
            db.add(
                TableSignup(
                    event_id=event_id,
                    discord_id=player["id"],
                    discord_name=player["name"][:100],
                    choices=player["choices"],
                )
            )
        db.commit()
        return True


def checkpoint(engine: Engine, event_id: str) -> None:
    with Session(engine) as db:
        event = db.get(Event, event_id)
        if not event or event.reaction_error or event.reaction_checkpoint is None:
            return
        db.execute(
            update(Event)
            .where(
                Event.id == event_id,
                Event.status == "open",
                Event.reaction_error.is_(None),
            )
            .values(reaction_checkpoint=min(time.time(), event.closes_at or 0))
        )
        db.commit()
