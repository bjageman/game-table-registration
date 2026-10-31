import logging
import time
from datetime import datetime
from typing import Any

from sqlalchemy import Engine, create_engine, or_, select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.discord_api import DiscordAPI, DiscordRateLimit
from app.models import Event

log = logging.getLogger(__name__)


class SnapshotMismatch(ValueError):
    pass


def answer_mapping(event: Event, poll: dict[str, Any]) -> dict[int, str]:
    expected = {
        f"{t['name']} · {t['capacity']} seats": str(t["name"]) for t in event.tables
    }
    answers = poll.get("answers", [])
    mapping: dict[int, str] = {}
    for answer in answers:
        label = answer.get("poll_media", {}).get("text")
        answer_id = answer.get("answer_id")
        if (
            label not in expected
            or not isinstance(answer_id, int)
            or answer_id in mapping
        ):
            raise SnapshotMismatch("Poll answers differ from the saved table snapshot")
        mapping[answer_id] = expected[label]
    if len(mapping) != len(expected) or set(mapping.values()) != set(expected.values()):
        raise SnapshotMismatch("Poll is missing table answers")
    saved_ids = {a["answer_id"] for a in (event.answers or [])}
    if saved_ids and saved_ids != set(mapping):
        raise SnapshotMismatch("Poll answer identifiers changed")
    if poll.get("allow_multiselect") is not True:
        raise SnapshotMismatch("Poll must allow multiple table choices")
    return mapping


def collect_snapshot(
    event: Event, discord: DiscordAPI, config: Settings
) -> list[dict[str, Any]]:
    if not event.message_id:
        raise SnapshotMismatch("No poll message is linked")
    started = time.monotonic()
    message = discord.bot(
        "GET", f"/channels/{config.discord_channel_id}/messages/{event.message_id}"
    )
    poll = message.get("poll", {})
    expiry = poll.get("expiry")
    if not expiry or datetime.fromisoformat(expiry).timestamp() > time.time():
        raise RuntimeError("Poll has not ended")
    results = poll.get("results", {})
    if results.get("is_finalized") is not True:
        raise RuntimeError("Discord has not finalized poll results yet")
    mapping = answer_mapping(event, poll)
    counts = {int(a["id"]): int(a["count"]) for a in results.get("answer_counts", [])}
    if any(key not in mapping or value < 0 for key, value in counts.items()):
        raise SnapshotMismatch("Final tally contains unknown answers or invalid counts")
    selected: dict[str, set[str]] = {}
    for answer_id, table in mapping.items():
        seen: set[str] = set()
        after = "0"
        while True:
            if time.monotonic() - started > 75:
                raise RuntimeError("Voter retrieval exceeded its time budget; retrying")
            response = discord.bot(
                "GET",
                f"/channels/{config.discord_channel_id}/polls/{event.message_id}/answers/{answer_id}",
                params={"limit": 100, "after": after},
            )
            users = response.get("users")
            if not isinstance(users, list):
                raise RuntimeError("Discord returned an invalid voter page")
            ids = [str(u.get("id", "")) for u in users]
            if any(not uid.isdigit() or int(uid) <= int(after) for uid in ids) or len(
                set(ids)
            ) != len(ids):
                raise RuntimeError("Voter pagination did not advance")
            for user, user_id in zip(users, ids, strict=True):
                seen.add(user_id)
                if not user.get("bot", False):
                    selected.setdefault(user_id, set()).add(table)
            if len(users) < 100:
                break
            after = str(max(map(int, ids)))
        if len(seen) != counts.get(answer_id, 0):
            raise RuntimeError("Voter pages do not match Discord's finalized tally")
    return [
        {"user_id": uid, "tables": sorted(tables)}
        for uid, tables in sorted(selected.items(), key=lambda item: int(item[0]))
    ]


def reconcile_event(
    engine: Engine, discord: DiscordAPI, config: Settings, event_id: str
) -> None:
    claimed_at = time.time()
    with Session(engine) as db:
        claimed = db.execute(
            update(Event)
            .where(
                Event.id == event_id,
                Event.guild_id == config.discord_guild_id,
                Event.status == "closed",
                or_(
                    Event.reconcile_after.is_(None), Event.reconcile_after <= claimed_at
                ),
            )
            .values(
                status="reconciling",
                operation_started_at=claimed_at,
                reconciliation_attempts=Event.reconciliation_attempts + 1,
            )
            .returning(Event.id)
        ).scalar_one_or_none()
        db.commit()
        if not claimed:
            return
        event = db.get(Event, event_id)
        assert event is not None
        try:
            snapshot = collect_snapshot(event, discord, config)
            db.execute(
                update(Event)
                .where(
                    Event.id == event_id,
                    Event.status == "reconciling",
                    Event.operation_started_at == claimed_at,
                )
                .values(
                    voter_snapshot=snapshot,
                    reconciled_at=time.time(),
                    status="reconciled",
                    operation_started_at=None,
                    reconcile_after=None,
                    last_error=None,
                )
            )
            db.commit()
        except Exception as failure:
            db.rollback()
            delay = min(300, 5 * 2 ** min(event.reconciliation_attempts, 6))
            if isinstance(failure, DiscordRateLimit):
                delay = max(delay, failure.retry_after)
            db.execute(
                update(Event)
                .where(
                    Event.id == event_id,
                    Event.status == "reconciling",
                    Event.operation_started_at == claimed_at,
                )
                .values(
                    status="needs_review"
                    if isinstance(failure, SnapshotMismatch)
                    else "closed",
                    reconcile_after=time.time() + delay,
                    last_error=str(failure)[:500],
                    operation_started_at=None,
                )
            )
            db.commit()


def tick(engine: Engine, discord: DiscordAPI, config: Settings) -> None:
    now = time.time()
    with Session(engine) as db:
        db.execute(
            update(Event)
            .where(
                Event.guild_id == config.discord_guild_id,
                Event.status == "reconciling",
                Event.operation_started_at < now - 120,
            )
            .values(status="closed", operation_started_at=None, reconcile_after=now)
        )
        db.commit()
        ids = list(
            db.scalars(
                select(Event.id).where(
                    Event.guild_id == config.discord_guild_id,
                    Event.status == "closed",
                    or_(Event.reconcile_after.is_(None), Event.reconcile_after <= now),
                )
            )
        )
    for event_id in ids:
        reconcile_event(engine, discord, config, event_id)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config = Settings()
    engine = create_engine(config.database_url, pool_pre_ping=True)
    discord = DiscordAPI(config)
    while True:
        try:
            tick(engine, discord, config)
        except Exception:
            log.exception("Reconciliation tick failed")
        time.sleep(5)


if __name__ == "__main__":
    main()
