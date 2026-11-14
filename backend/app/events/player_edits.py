"""One table-scoped entry point for organizer player additions and removals."""

from fastapi import HTTPException
from sqlalchemy import Engine, update
from sqlalchemy.orm import Session

from app.assignments.waitlists import add_player as add_waitlisted
from app.assignments.withdrawals import manager_add, manager_remove
from app.discord.event_threads import queue_member
from app.events.table_membership import set_removed
from app.models import Event, EventManagerSignup, TableSignup
from app.players.player_profiles import for_event


def remove_signup_choice(db: Session, event: Event, player_id: str, table: str) -> None:
    """Remove the choice from every persisted signup source."""
    signup = db.get(TableSignup, (event.id, player_id))
    if signup is not None:
        signup.choices = [choice for choice in signup.choices if choice != table]
    override = db.get(EventManagerSignup, (event.id, player_id))
    if override is not None:
        override.choices = [choice for choice in override.choices if choice != table]
    if event.test_signups:
        event.test_signups = {
            **event.test_signups,
            "players": [
                {
                    **player,
                    "choices": [
                        choice for choice in player["choices"] if choice != table
                    ],
                }
                if player["id"] == player_id
                else player
                for player in event.test_signups["players"]
            ],
        }
    set_removed(db, event.id, player_id, table, True)


def edit_player(
    engine: Engine,
    guild_id: str,
    event_id: str,
    player_id: str,
    table: str,
    *,
    adding: bool,
    waitlist: bool = False,
    name: str = "",
    allow_known: bool = True,
) -> None:
    with Session(engine) as db:
        event = db.get(Event, event_id)
        if event is None or event.guild_id != guild_id:
            raise HTTPException(404, "Event not found")
        if table not in {item["name"] for item in event.tables}:
            raise HTTPException(
                409 if event.status in {"review", "assigned"} else 422, "Unknown table"
            )
        if event.archived_at or event.status not in {
            "draft",
            "scheduled",
            "open",
            "review",
            "assigned",
        }:
            raise HTTPException(409, "This event cannot be edited")
        placed = event.status in {"review", "assigned"}
        if not placed:
            if waitlist:
                raise HTTPException(409, "Waitlists are available after assignments")
            claimed = db.execute(
                update(Event)
                .where(
                    Event.id == event_id,
                    Event.status.in_(["draft", "scheduled", "open"]),
                    Event.archived_at.is_(None),
                )
                .values(status=Event.status)
                .returning(Event.id)
            ).scalar_one_or_none()
            if not claimed:
                raise HTTPException(409, "This event cannot be edited")
            if adding:
                profile = for_event(event).get(db, player_id)
                if player_id.startswith("test-") and (
                    profile is None or not profile.is_test
                ):
                    raise HTTPException(404, "Player not found")
                override = db.get(EventManagerSignup, (event_id, player_id))
                if override is None:
                    override = EventManagerSignup(
                        event_id=event_id,
                        discord_id=player_id,
                        discord_name=name.strip(),
                        choices=[],
                        removed=False,
                    )
                    db.add(override)
                if override.removed:
                    retained = set(override.choices)
                    for item in event.tables:
                        if item["name"] not in retained:
                            remove_signup_choice(db, event, player_id, item["name"])
                override.discord_name = name.strip()
                override.choices = sorted(set(override.choices) | {table})
                override.removed = False
                queue_member(db, event, player_id)
            else:
                remove_signup_choice(db, event, player_id, table)
            set_removed(db, event_id, player_id, table, not adding)
            event.signup_roster_checked_at = None
            db.commit()
            return
    if not adding:
        changed = manager_remove(
            engine, guild_id, event_id, player_id, table, waitlist_only=waitlist
        )
    elif waitlist:
        changed = add_waitlisted(engine, guild_id, event_id, player_id, table)
    else:
        changed = manager_add(
            engine, guild_id, event_id, player_id, table, allow_known_player=allow_known
        )
    if not changed:
        raise HTTPException(409, "Player cannot be changed on this table")
