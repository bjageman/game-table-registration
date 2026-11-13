"""Table-specific signup logic shared by Discord Gateway interactions."""

import time
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.discord_format import clean
from app.event_threads import queue_member
from app.models import Event, EventManagerSignup, SignupInteraction, TableSignup
from app.signup_messages import signup_body


def publication(
    event: Event, closes_at: float, include_roster: bool = True
) -> dict[str, Any]:
    return {
        **signup_body(event, "custom", closes_at, include_roster),
        "allowed_mentions": {"parse": []},
        "components": [
            {
                "type": 1,
                "components": [
                    {
                        "type": 2,
                        "style": 1,
                        "label": "Choose tables / My signup",
                        "custom_id": f"signup:open:{event.id}",
                    }
                ],
            }
        ],
    }


def players(
    db: Session, event: Event, weights: dict[str, float]
) -> list[dict[str, Any]]:
    return [
        {
            "id": row.discord_id,
            "name": row.discord_name,
            "choices": list(row.choices),
            "weight": weights.get(row.discord_id, 5.0),
        }
        for row in db.scalars(
            select(TableSignup)
            .where(TableSignup.event_id == event.id)
            .order_by(TableSignup.discord_id)
        )
        if row.choices
    ]


def table_rows(db: Session, event: Event) -> list[dict[str, Any]]:
    participants = players(db, event, {})
    return [
        {
            "name": table["name"],
            "players": sorted(
                [
                    {"id": p["id"], "name": p["name"]}
                    for p in participants
                    if table["name"] in p["choices"]
                ],
                key=lambda p: p["name"].casefold(),
            ),
        }
        for table in event.tables
    ]


def apply_manager_signups(
    db: Session, event: Event, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    overrides = list(
        db.scalars(
            select(EventManagerSignup).where(EventManagerSignup.event_id == event.id)
        )
    )
    removed = {override.discord_id for override in overrides if override.removed}
    additions = {
        override.discord_id: override for override in overrides if not override.removed
    }
    by_table = {row["name"]: row for row in rows}
    for row in rows:
        row["players"] = [p for p in row["players"] if p["id"] not in removed]
    for override in additions.values():
        for table_name in override.choices:
            table_row = by_table.get(table_name)
            if table_row is None or any(
                p["id"] == override.discord_id for p in table_row["players"]
            ):
                continue
            table_row["players"].append(
                {"id": override.discord_id, "name": override.discord_name}
            )
    return rows


def apply_manager_players(
    db: Session,
    event: Event,
    participants: list[dict[str, Any]],
    weights: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    overrides = list(
        db.scalars(
            select(EventManagerSignup).where(EventManagerSignup.event_id == event.id)
        )
    )
    by_id = {player["id"]: dict(player) for player in participants}
    for override in overrides:
        if override.removed:
            by_id.pop(override.discord_id, None)
        elif override.choices:
            player = by_id.setdefault(
                override.discord_id,
                {
                    "id": override.discord_id,
                    "name": override.discord_name,
                    "choices": [],
                    "weight": (weights or {}).get(override.discord_id, 5.0),
                },
            )
            player["name"] = override.discord_name
            player["choices"] = sorted(
                set(player.get("choices", [])) | set(override.choices)
            )
    return list(by_id.values())


def private_message(content: str) -> dict[str, Any]:
    return {
        "type": 4,
        "data": {"content": content, "flags": 64, "allowed_mentions": {"parse": []}},
    }


def menu(event: Event, choices: list[str], notice: str) -> dict[str, Any]:
    current = ", ".join(clean(name) for name in choices) or "None"
    return {
        "content": (
            f"**{clean(event.title)} — Your table signup**\n{notice}\n"
            f"Saved tables: {current}\n\n"
            "Select every table you would attend. Selecting saves your complete "
            "selection and replaces your previous choices. "
            "Signing up enters the lottery; it does not guarantee a seat.\n"
            f"Signups close <t:{int(event.closes_at or 0)}:R>."
        ),
        "allowed_mentions": {"parse": []},
        "components": [
            {
                "type": 1,
                "components": [
                    {
                        "type": 3,
                        "custom_id": f"signup:select:{event.id}",
                        "placeholder": "Choose your tables",
                        "min_values": 1,
                        "max_values": len(event.tables),
                        "options": [
                            {
                                "label": t["name"],
                                "value": str(index),
                                "description": f"{t['capacity']} seats",
                                "default": t["name"] in choices,
                            }
                            for index, t in enumerate(event.tables)
                        ],
                    }
                ],
            },
            {
                "type": 1,
                "components": [
                    {
                        "type": 2,
                        "style": 2,
                        "label": "Withdraw from all tables",
                        "custom_id": f"signup:withdraw:{event.id}",
                        "disabled": not choices,
                    }
                ],
            },
        ],
    }


def handle(engine: Engine, config: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("application_id") != config.discord_client_id:
        raise HTTPException(401, "Wrong Discord application")
    if payload.get("type") == 1:
        return {"type": 1}
    try:
        if payload["type"] != 3:
            raise ValueError
        prefix, action, event_id = payload["data"]["custom_id"].split(":")
        if prefix != "signup" or action not in ("open", "select", "withdraw"):
            raise ValueError
        if payload["data"]["component_type"] != (3 if action == "select" else 2):
            raise ValueError
        user = payload["member"]["user"]
        user_id = user["id"]
        interaction_id = payload["id"]
        if (
            user.get("bot")
            or not isinstance(user_id, str)
            or not user_id.isdecimal()
            or len(user_id) > 32
            or not isinstance(interaction_id, str)
            or not interaction_id.isdecimal()
            or len(interaction_id) > 32
        ):
            raise ValueError
        name = (
            payload["member"].get("nick") or user.get("global_name") or user["username"]
        )
        if not isinstance(name, str) or not name.strip():
            raise ValueError
    except (KeyError, ValueError, TypeError, AttributeError):
        return private_message(
            "This signup control is invalid. Open the event message again."
        )

    with Session(engine) as db:
        # Both SQLite and PostgreSQL serialize this against closing/deletion and
        # other signup edits. Keep the lock through receipt and selection commit.
        changed = db.execute(
            update(Event)
            .where(Event.id == event_id)
            .values(status=Event.status)
            .returning(Event.id)
        ).scalar_one_or_none()
        event = db.get(Event, event_id) if changed else None
        if (
            event is None
            or event.signup_mode != "custom"
            or payload.get("guild_id") != event.guild_id
            or payload.get("channel_id") != event.channel_id
        ):
            return private_message("This event is no longer available in this channel.")
        message = payload.get("message", {})
        if action == "open":
            valid_source = message.get("id") == event.message_id
        else:
            # Selection controls exist only in this app's private menu.
            valid_source = (
                isinstance(message.get("flags"), int)
                and bool(message["flags"] & 64)
                and message.get("author", {}).get("id") == config.discord_client_id
            )
        if not valid_source:
            return private_message("Open your signup from the original event message.")
        receipt = db.get(SignupInteraction, interaction_id)
        if receipt is not None:
            return receipt.response
        if (
            event.status != "open"
            or not event.closes_at
            or event.closes_at <= time.time()
        ):
            return private_message(
                "Signups are closed. Your saved table choices have not changed."
            )
        signup = db.get(TableSignup, (event_id, user_id))
        choices = list(signup.choices) if signup else []
        notice = "Your saved choices are shown below."
        if action == "select":
            values = payload["data"].get("values")
            valid_values = {str(i) for i in range(len(event.tables))}
            if (
                not isinstance(values, list)
                or not values
                or any(not isinstance(v, str) or v not in valid_values for v in values)
                or len(set(values)) != len(values)
            ):
                return private_message(
                    "Select valid tables from the event's signup menu."
                )
            choices = [
                t["name"] for i, t in enumerate(event.tables) if str(i) in values
            ]
            if signup is None:
                signup = TableSignup(event_id=event_id, discord_id=user_id)
                db.add(signup)
            signup.discord_name = name[:100]
            signup.choices = choices
            manager_override = db.get(EventManagerSignup, (event_id, user_id))
            if manager_override is not None and manager_override.removed:
                manager_override.removed = False
            if choices:
                queue_member(db, event, user_id)
            notice = "Your table signup has been saved."
        elif action == "withdraw":
            if signup is not None:
                db.delete(signup)
            choices = []
            notice = "You have withdrawn from all tables."
        response: dict[str, Any] = {
            "type": 4 if action == "open" else 7,
            "data": menu(event, choices, notice),
        }
        if action == "open":
            response["data"]["flags"] = 64
        else:
            event.signup_roster_checked_at = None
        db.add(
            SignupInteraction(id=interaction_id, event_id=event_id, response=response)
        )
        db.commit()
        return response
