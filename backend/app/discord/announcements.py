"""Durable assignment announcements; never rerun the lottery for delivery."""

import time
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Engine, case, func, or_, select, update
from sqlalchemy.orm import Session

from app.assignments.assignment_finalization import complete_review_delivery
from app.discord.delivery import (
    UNCONFIRMED_DELIVERY,
    announcement_failure_values,
    claim_delivery,
    complete_delivery,
    resolve_message,
    retry_delay,
    save_delivery,
)
from app.discord.discord_api import DiscordAPI, DiscordRequestError
from app.discord.discord_format import (
    sanitize_user_mentions,
)
from app.discord.event_messages import build_assignment_messages
from app.discord.event_threads import resolve_update_channel
from app.events.signup_warnings import can_send as can_send_warning
from app.models import Announcement, DiscordScheduledEvent, Event, LotteryRun
from app.settings.assignment_preferences import announce_changes

PRIMARY_KINDS = ("assignment", "instructions", "refresh")


def refresh_assignment_posts(
    engine: Engine, discord: DiscordAPI, event_id: str
) -> str | None:
    """Replace tracked assignment rosters with current saved placements."""
    from app.assignments.withdrawals import current_result

    with Session(engine) as db:
        event = db.get(Event, event_id)
        run = db.get(LotteryRun, event_id)
        if event is None or run is None or event.archived_at:
            return None
        rows = list(
            db.scalars(
                select(Announcement)
                .where(
                    Announcement.event_id == event_id, Announcement.kind == "assignment"
                )
                .order_by(Announcement.part)
            )
        )
        if not rows:
            return None
        if any(
            row.state != "sent" or not row.message_id or row.deleted_at for row in rows
        ):
            raise HTTPException(503, "Assignment posts are not ready for editing")
        refreshed = build_assignment_messages(
            event,
            rows[0].channel_id,
            current_result(db, run),
            run.snapshot,
            notify=False,
        )
        if len(refreshed) > len(rows):
            raise HTTPException(
                409, "Updated assignments need more messages than the original post"
            )
        for i, row in enumerate(rows):
            edit = (
                {
                    "content": refreshed[i]["content"],
                    "embeds": refreshed[i]["embeds"],
                    "allowed_mentions": {"parse": [], "users": []},
                }
                if i < len(refreshed)
                else {
                    "content": f"Assignments updated above (part {i + 1}).",
                    "embeds": [],
                    "allowed_mentions": {"parse": [], "users": []},
                }
            )
            try:
                discord.at(event.guild_id, row.channel_id).edit_announcement(
                    row.channel_id, str(row.message_id), edit
                )
            except DiscordRequestError as failure:
                if failure.discord_status == 404:
                    raise HTTPException(
                        409, "An assignment message is missing from Discord"
                    ) from None
                raise
            row.payload = {**row.payload, **edit}
        db.commit()
        return rows[0].message_id


def deliver_event(
    engine: Engine,
    discord: DiscordAPI,
    event_id: str,
    limit: int = 1,
    *,
    kind: str | None = None,
) -> None:
    for _ in range(limit):
        now = time.time()
        with Session(engine) as db:
            row = db.scalar(
                select(Announcement)
                .where(
                    Announcement.event_id == event_id,
                    Announcement.state.in_(["pending", "sending"]),
                    *([Announcement.kind == kind] if kind else []),
                )
                .order_by(
                    case((Announcement.kind.in_(PRIMARY_KINDS), 0), else_=1),
                    Announcement.part,
                )
                .limit(1)
            )
            event = db.get(Event, event_id)
            if row is not None and row.state == "pending" and not row.unknown:
                row.payload = sanitize_user_mentions(row.payload)
            expired_warning = bool(
                row and row.kind == "warning" and not can_send_warning(event, now)
            )
            if expired_warning:
                assert row is not None
                if not row.unknown and row.state != "sending":
                    row.state = "sent"
                    row.deleted_at = now
                    row.token = None
                    row.lease_until = None
                    db.commit()
                    continue
            if (
                row is not None
                and row.kind
                in ("promotion", "instructions", "refresh", "thread_starter")
                and event
                and (
                    event.archived_at
                    or (row.kind == "promotion" and not announce_changes(db, event))
                )
            ):
                if row.unknown or row.state == "sending" or row.message_id:
                    return
                row.state = "sent"
                row.deleted_at = now
                row.token = None
                row.lease_until = None
                db.commit()
                continue
            if (
                row is None
                or row.state == "needs_review"
                or (row.next_attempt > now and not expired_warning)
            ):
                return
            recovering = row.state == "sending"
            unknown = row.unknown or recovering
            attempted_at = row.attempted_at or now
            token = claim_delivery(db, Announcement, row.id, now=now, attempted_at=now)
            db.commit()
            if token is None:
                return
            db.refresh(row)
            row_id, channel_id, payload, attempts = (
                row.id,
                row.channel_id,
                row.payload,
                row.attempts,
            )
            row_kind = row.kind
        sending_message = False
        try:
            if row_kind in ("promotion", "warning") and not unknown:
                channel_id = resolve_update_channel(
                    engine, discord, event_id, channel_id
                )
                with Session(engine) as db:
                    db.execute(
                        update(Announcement)
                        .where(
                            Announcement.id == row_id,
                            Announcement.token == token,
                        )
                        .values(channel_id=channel_id)
                    )
                    db.commit()
            if row_kind == "warning" and not unknown:
                with Session(engine) as db:
                    if not can_send_warning(db.get(Event, event_id), time.time()):
                        db.execute(
                            update(Announcement)
                            .where(
                                Announcement.id == row_id,
                                Announcement.token == token,
                            )
                            .values(
                                state="sent",
                                deleted_at=time.time(),
                                token=None,
                                lease_until=None,
                            )
                        )
                        db.commit()
                        continue
            if row_kind == "refresh":
                message_id = refresh_assignment_posts(engine, discord, event_id)
            else:
                sending_message = not unknown
                message_id = resolve_message(
                    discord, channel_id, payload, attempted_at, unknown=unknown
                )
                if message_id is None:
                    raise RuntimeError(UNCONFIRMED_DELIVERY)
            if row_kind == "instructions":
                assert message_id is not None
                discord.seed_reactions(message_id, ["❌"])
            deleted_at = time.time() if row_kind == "refresh" else None
            if row_kind == "promotion":
                assert message_id is not None
                with Session(engine) as db:
                    event = db.get(Event, event_id)
                    archived = bool(event and event.archived_at)
                if archived:
                    try:
                        discord.bot(
                            "DELETE", f"/channels/{channel_id}/messages/{message_id}"
                        )
                        deleted_at = time.time()
                    except Exception:
                        # Keep the message ID so archived-event cleanup can retry.
                        pass
            with Session(engine) as db:
                complete_delivery(
                    db, Announcement, row_id, token, message_id, deleted_at=deleted_at
                )
                if row_kind == "assignment":
                    complete_review_delivery(db, event_id)
                    db.execute(
                        update(DiscordScheduledEvent)
                        .where(
                            DiscordScheduledEvent.event_id == event_id,
                            DiscordScheduledEvent.state != "creating",
                        )
                        .values(checked_at=None)
                    )
                db.commit()
        except Exception as failure:
            if row_kind == "refresh":
                needs_review = (
                    isinstance(failure, HTTPException) and failure.status_code == 409
                ) or (
                    isinstance(failure, DiscordRequestError)
                    and failure.discord_status in (400, 404)
                )
                with Session(engine) as db:
                    db.execute(
                        update(Announcement)
                        .where(Announcement.id == row_id, Announcement.token == token)
                        .values(
                            state="needs_review" if needs_review else "pending",
                            error=str(getattr(failure, "detail", failure)),
                            unknown=False,
                            token=None,
                            lease_until=None,
                            next_attempt=time.time() + retry_delay(failure, attempts),
                        )
                    )
                    db.commit()
                return
            with Session(engine) as db:
                save_delivery(
                    db,
                    Announcement,
                    row_id,
                    token,
                    **announcement_failure_values(
                        failure,
                        unknown=unknown,
                        sending=sending_message,
                        attempts=attempts,
                        now=time.time(),
                    ),
                )
                db.commit()
            return


def dispatch_due(engine: Engine, client_for: Callable[[str, str], DiscordAPI]) -> None:
    with Session(engine) as db:
        first = (
            select(
                Announcement.event_id,
                func.coalesce(
                    func.min(
                        case((Announcement.kind.in_(PRIMARY_KINDS), Announcement.part))
                    ),
                    func.min(Announcement.part),
                ).label("part"),
            )
            .where(Announcement.state.in_(["pending", "sending"]))
            .group_by(Announcement.event_id)
            .subquery()
        )
        rows = list(
            db.execute(
                select(Announcement.event_id, Event.guild_id, Announcement.channel_id)
                .join(Event, Event.id == Announcement.event_id)
                .join(
                    first,
                    (first.c.event_id == Announcement.event_id)
                    & (first.c.part == Announcement.part),
                )
                .where(
                    or_(
                        Announcement.kind != "promotion",
                        Event.archived_at.is_(None),
                    ),
                    Announcement.state.in_(["pending", "sending"]),
                    # Expired warnings must be canceled/reconciled even during
                    # backoff, so they cannot hold later assignment posts up.
                    or_(
                        Announcement.next_attempt <= time.time(),
                        Announcement.kind == "warning",
                    ),
                    or_(
                        Announcement.token.is_(None),
                        Announcement.lease_until <= time.time(),
                    ),
                )
                .order_by(Announcement.next_attempt)
                .limit(20)
            )
        )
    for event_id, guild_id, channel_id in rows:
        deliver_event(engine, client_for(guild_id, channel_id), event_id, limit=5)


def status(engine: Engine, event_id: str, guild_id: str) -> dict[str, Any]:
    with Session(engine) as db:
        refresh = db.scalar(
            select(Announcement)
            .where(Announcement.event_id == event_id, Announcement.kind == "refresh")
            .order_by(Announcement.part.desc())
            .limit(1)
        )
        rows = list(
            db.scalars(
                select(Announcement)
                .where(
                    Announcement.event_id == event_id,
                    Announcement.kind.in_(["assignment", "instructions"]),
                )
                .order_by(Announcement.part)
            )
        )
        if not rows:
            return {
                "status": "unavailable",
                "error": None,
                "url": None,
                "update_pending": False,
                "update_error": None,
            }
        state = (
            "deleted"
            if all(row.deleted_at for row in rows)
            else "sent"
            if all(row.state == "sent" for row in rows)
            else "needs_review"
            if any(row.state == "needs_review" for row in rows)
            else "pending"
        )
        first = next(
            (row for row in rows if row.message_id and not row.deleted_at), None
        )
        return {
            "status": state,
            "error": next((row.error for row in rows if row.error), None),
            "update_pending": bool(refresh and refresh.state in ("pending", "sending")),
            "update_error": refresh.error
            if refresh and refresh.state == "needs_review"
            else None,
            "url": f"https://discord.com/channels/{guild_id}/{first.channel_id}/{first.message_id}"
            if first
            else None,
        }
