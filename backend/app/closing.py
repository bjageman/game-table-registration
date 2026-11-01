"""Close a Discord poll and commit exactly one immutable lottery result."""

import secrets
import time
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Engine, or_, select, update
from sqlalchemy.orm import Session

from app.announcements import enqueue
from app.discord_api import DiscordAPI
from app.lottery import VERSION, GuaranteeConflict, assign
from app.models import Event, LotteryRun, PlayerProfile

LEASE_SECONDS = 120


class Pending(Exception):
    pass


def poll_data(message: dict[str, Any]) -> tuple[dict[str, Any], float]:
    try:
        poll = message["poll"]
        expiry = datetime.fromisoformat(poll["expiry"])
        if expiry.tzinfo is None:
            raise ValueError("Missing timezone")
        return poll, expiry.timestamp()
    except (KeyError, TypeError, ValueError):
        raise HTTPException(502, "Discord returned an unreadable poll") from None


def reconcile(
    discord: DiscordAPI,
    message_id: str,
    tables: list[dict[str, Any]],
    saved_answers: list[dict[str, Any]],
    weights: dict[str, float],
) -> tuple[dict[str, Any], float]:
    poll, ended_at = poll_data(discord.poll_message(message_id))
    results = poll.get("results") or {}
    if ended_at > time.time() or results.get("is_finalized") is not True:
        raise Pending(
            "Discord is finalizing the poll. Placements have not been drawn yet."
        )
    try:
        answers = poll["answers"]
        expected = {f"{t['name']} · {t['capacity']} seats": t["name"] for t in tables}
        ids = {a["poll_media"]["text"]: a["answer_id"] for a in answers}
        if (
            set(ids) != set(expected)
            or len(ids) != len(answers)
            or len(set(ids.values())) != len(ids)
        ):
            raise ValueError("Poll answers changed")
        if any(not isinstance(i, int) or isinstance(i, bool) for i in ids.values()):
            raise ValueError("Invalid answer IDs")
        if {a["answer_id"] for a in saved_answers} != set(ids.values()):
            raise ValueError("Stored answer IDs do not match the poll")
        counts = {c["id"]: c["count"] for c in results["answer_counts"]}
        if len(counts) != len(results["answer_counts"]) or not set(counts) <= set(
            ids.values()
        ):
            raise ValueError("Invalid result counts")
        if any(
            not isinstance(n, int) or isinstance(n, bool) or n < 0
            for n in counts.values()
        ):
            raise ValueError("Invalid result count")
    except (KeyError, TypeError, ValueError):
        raise HTTPException(
            502, "Could not verify the finalized Discord poll"
        ) from None
    players: dict[str, dict[str, Any]] = {}
    for label, name in expected.items():
        answer_id = ids[label]
        users = discord.voter_users(message_id, answer_id)
        if len(users) != counts.get(answer_id, 0):
            raise Pending(
                "Discord's voter list is incomplete. No placements have been drawn."
            )
        for user in users:
            if user.get("bot"):
                continue
            pid = str(user["id"])
            player = players.setdefault(
                pid,
                {
                    "id": pid,
                    "name": user.get("global_name") or user["username"],
                    "choices": [],
                    "weight": weights.get(pid, 1.0),
                },
            )
            player["choices"].append(name)
    return {
        "tables": tables,
        "players": [players[pid] for pid in sorted(players)],
    }, ended_at


def close_and_assign(
    engine: Engine, discord: DiscordAPI, event_id: str, moderator: str, channel_id: str
) -> bool:
    token = secrets.token_hex(16)
    now = time.time()
    with Session(engine) as db:
        event = db.get(Event, event_id)
        if event is None:
            raise HTTPException(404, "Event not found")
        if event.status == "assigned":
            if db.get(LotteryRun, event_id) is None:
                raise HTTPException(503, "Saved placements are unavailable")
            return True
        if event.status not in ("open", "closing") or not event.message_id:
            raise HTTPException(409, "Only open signups can be closed")
        previous_status = event.status
        weights = event.close_weights
        if weights is None:
            weights = {
                p.discord_id: p.weighting
                for p in db.scalars(
                    select(PlayerProfile).where(
                        PlayerProfile.guild_id == event.guild_id
                    )
                )
            }
        guarantees = event.close_guarantees
        if guarantees is None:
            guarantees = {
                p.discord_id: {
                    "guaranteed_seat": True,
                    "guaranteed_table": p.guaranteed_table,
                }
                for p in db.scalars(
                    select(PlayerProfile).where(
                        PlayerProfile.guild_id == event.guild_id,
                        PlayerProfile.guaranteed_seat.is_(True),
                    )
                )
            }
        seed = event.close_seed or secrets.token_hex(32)
        claimed = db.execute(
            update(Event)
            .where(
                Event.id == event_id,
                Event.status.in_(["open", "closing"]),
                or_(
                    Event.close_token.is_(None),
                    Event.close_started_at <= now - LEASE_SECONDS,
                ),
            )
            .values(
                status="closing",
                close_token=token,
                close_started_at=now,
                close_seed=seed,
                close_weights=weights,
                close_guarantees=guarantees,
                close_error=None,
            )
            .returning(Event.id)
        ).scalar_one_or_none()
        db.commit()
        if not claimed:
            raise HTTPException(
                409,
                "Signup closing is already in progress. Refresh to check its status.",
            )
        db.refresh(event)
        message_id = event.message_id
        tables = [dict(t) for t in event.tables]
        answers = list(event.answers or [])
        test_population = event.test_signups
        assert message_id is not None

    def with_guarantees(snapshot: dict[str, Any]) -> dict[str, Any]:
        for player in snapshot["players"]:
            player.update(guarantees.get(player["id"], {}))
        return snapshot

    preflight = True
    try:
        if guarantees:
            rows = discord.table_signups(message_id, tables)
            participants: dict[str, dict[str, Any]] = {}
            for row in rows:
                for player in row["players"]:
                    entry = participants.setdefault(
                        player["id"],
                        {
                            **player,
                            "choices": [],
                            "weight": weights.get(player["id"], 1.0),
                        },
                    )
                    entry["choices"].append(row["name"])
            if test_population:
                for player in test_population["players"]:
                    participants[player["id"]] = {
                        **player,
                        "weight": weights.get(player["id"], 1.0),
                    }
            assign(
                with_guarantees(
                    {"tables": tables, "players": list(participants.values())}
                ),
                seed,
            )
        preflight = False
        poll, expiry = poll_data(discord.poll_message(message_id))
        if expiry > time.time() and not (poll.get("results") or {}).get("is_finalized"):
            discord.end_poll(message_id)
        snapshot, ended_at = reconcile(discord, message_id, tables, answers, weights)
        if test_population:
            snapshot["is_test"] = True
            snapshot["players"].extend(
                {
                    "id": player["id"],
                    "name": player["name"],
                    "choices": player["choices"],
                    "weight": weights.get(player["id"], 1.0),
                    "is_test": True,
                }
                for player in test_population["players"]
            )
        result = assign(with_guarantees(snapshot), seed)
        with Session(engine) as db:
            changed = db.execute(
                update(Event)
                .where(
                    Event.id == event_id,
                    Event.status == "closing",
                    Event.close_token == token,
                )
                .values(
                    status="assigned",
                    close_token=None,
                    close_error=None,
                    closes_at=ended_at,
                )
                .returning(Event.id)
            ).scalar_one_or_none()
            if not changed:
                raise HTTPException(
                    409, "Closing ownership changed. Refresh to see the saved result."
                )
            db.add(
                LotteryRun(
                    event_id=event_id,
                    version=VERSION,
                    seed=seed,
                    snapshot=snapshot,
                    result=result,
                    created_by=moderator,
                    created_at=time.time(),
                )
            )
            enqueue(db, event, event.channel_id or channel_id, result, snapshot)
            db.commit()
        return True
    except Exception as failure:
        if isinstance(failure, GuaranteeConflict):
            # Permit correcting reservations and retrying; never save a partial draw.
            with Session(engine) as db:
                db.execute(
                    update(Event)
                    .where(Event.id == event_id, Event.close_token == token)
                    .values(
                        status=previous_status if preflight else "closing",
                        close_token=None,
                        close_guarantees=None,
                        close_weights=None,
                        close_error=str(failure)[:500],
                    )
                )
                db.commit()
            raise HTTPException(409, str(failure)) from None
        pending = isinstance(failure, Pending)
        message = (
            str(failure)
            if pending
            else "Closing could not be completed. Retry Close Signups to finish safely."
        )
        with Session(engine) as db:
            db.execute(
                update(Event)
                .where(Event.id == event_id, Event.close_token == token)
                .values(close_token=None, close_error=message[:500])
            )
            db.commit()
        if pending:
            return False
        if isinstance(failure, HTTPException):
            raise
        raise HTTPException(
            502,
            "Could not confirm placement completion. "
            "Refresh or retry Close Signups safely.",
        ) from None
