"""Durable private promotion notices, independent of public announcements."""

import hashlib
import logging
import secrets
import time
import uuid

from sqlalchemy import Engine, or_, select, update
from sqlalchemy.orm import Session

from app.discord.discord_api import DiscordAPI, DiscordRequestError
from app.discord.discord_format import clean
from app.models import Event, LotteryRun, PromotionDM
from app.settings.assignment_preferences import for_event

logger = logging.getLogger(__name__)
BUTTON_PREFIX = "promotion:withdraw:"


def enqueue(db: Session, event: Event, player_id: str, table_name: str) -> None:
    """Queue in the same locked transaction that assigns the promoted player."""
    preference = for_event(db, event)
    if (
        not preference
        or not preference.dm_waitlist_promotions
        or not player_id.isascii()
        or not player_id.isdecimal()
        or event.archived_at
        or event.starts_at <= time.time()
    ):
        return
    if db.scalar(
        select(PromotionDM.id).where(
            PromotionDM.event_id == event.id, PromotionDM.discord_id == player_id
        )
    ):
        return
    notice_id = str(uuid.uuid4())
    content = (
        f"Congratulations! You have been added to **{clean(table_name)}** "
        f"from the waitlist for **{clean(event.title)}**.\n"
        f"Event: <t:{int(event.starts_at)}:F>\n\n"
        "If you cannot make it, use **Give up my seat** below to withdraw "
        "and free the seat for the next waitlisted player."
    )
    if event.message_id and event.channel_id:
        content += (
            f"\n[Event signup](https://discord.com/channels/{event.guild_id}/"
            f"{event.channel_id}/{event.message_id})"
        )
    now = time.time()
    db.add(
        PromotionDM(
            id=notice_id,
            event_id=event.id,
            discord_id=player_id,
            table_name=table_name,
            created_at=now,
            next_attempt=now,
            payload={
                "content": content,
                "allowed_mentions": {"parse": [], "users": []},
                "nonce": hashlib.sha256(notice_id.encode()).hexdigest()[:24],
                "enforce_nonce": True,
                "components": [
                    {
                        "type": 1,
                        "components": [
                            {
                                "type": 2,
                                "style": 4,
                                "label": "Give up my seat",
                                "custom_id": f"{BUTTON_PREFIX}{notice_id}",
                            }
                        ],
                    }
                ],
            },
        )
    )


def _eligible(db: Session, notice: PromotionDM) -> bool:
    from app.assignments.withdrawals import current_result

    event = db.get(Event, notice.event_id)
    if (
        event is None
        or event.status != "assigned"
        or event.archived_at
        or event.starts_at <= time.time()
    ):
        return False
    preference = for_event(db, event)
    run = db.get(LotteryRun, event.id)
    return bool(
        preference
        and preference.dm_waitlist_promotions
        and run
        and current_result(db, run)["assignments"].get(notice.discord_id)
        == notice.table_name
    )


def deliver(engine: Engine, discord: DiscordAPI, notice_id: str) -> None:
    now = time.time()
    token = secrets.token_hex(16)
    with Session(engine) as db:
        notice = db.get(PromotionDM, notice_id)
        if (
            notice is None
            or notice.state not in ("pending", "sending")
            or notice.next_attempt > now
        ):
            return
        unknown = notice.unknown or notice.state == "sending"
        attempted_at = notice.attempted_at or now
        changed = db.execute(
            update(PromotionDM)
            .where(
                PromotionDM.id == notice_id,
                PromotionDM.state.in_(["pending", "sending"]),
                or_(PromotionDM.token.is_(None), PromotionDM.lease_until <= now),
            )
            .values(
                state="sending",
                token=token,
                lease_until=now + 90,
                attempts=PromotionDM.attempts + 1,
                attempted_at=attempted_at,
            )
            .returning(PromotionDM.id)
        ).scalar_one_or_none()
        if changed is None:
            return
        db.refresh(notice)
        if not _eligible(db, notice):
            notice.state = "canceled"
            notice.token = None
            notice.lease_until = None
            db.commit()
            return
        recipient, channel, body, attempts = (
            notice.discord_id,
            notice.channel_id,
            notice.payload,
            notice.attempts,
        )
        db.commit()
    sending = False
    try:
        if channel is None:
            channel = discord.open_dm(recipient)
            with Session(engine) as db:
                changed = db.execute(
                    update(PromotionDM)
                    .where(
                        PromotionDM.id == notice_id,
                        PromotionDM.token == token,
                    )
                    .values(channel_id=channel)
                    .returning(PromotionDM.id)
                ).scalar_one_or_none()
                db.commit()
                if not changed:
                    return
        if unknown:
            message_id = discord.find_announcement(channel, body, attempted_at)
            if message_id is None:
                with Session(engine) as db:
                    db.execute(
                        update(PromotionDM)
                        .where(
                            PromotionDM.id == notice_id,
                            PromotionDM.token == token,
                        )
                        .values(
                            state="needs_review",
                            unknown=True,
                            token=None,
                            lease_until=None,
                            error=(
                                "Private message delivery could not be confirmed; "
                                "no duplicate was sent."
                            ),
                        )
                    )
                    db.commit()
                return
        else:
            sending = True
            message_id = str(discord.send_announcement(channel, body)["id"])
        with Session(engine) as db:
            db.execute(
                update(PromotionDM)
                .where(
                    PromotionDM.id == notice_id,
                    PromotionDM.token == token,
                )
                .values(
                    state="sent",
                    message_id=message_id,
                    unknown=False,
                    token=None,
                    lease_until=None,
                    error=None,
                )
            )
            db.commit()
    except Exception as error:
        status = (
            error.discord_status if isinstance(error, DiscordRequestError) else None
        )
        ambiguous = unknown or (
            sending and (not isinstance(error, DiscordRequestError) or error.ambiguous)
        )
        terminal = status in (400, 403, 404) or attempts >= 8
        retry_after = error.retry_after if isinstance(error, DiscordRequestError) else 0
        with Session(engine) as db:
            db.execute(
                update(PromotionDM)
                .where(
                    PromotionDM.id == notice_id,
                    PromotionDM.token == token,
                )
                .values(
                    state="blocked"
                    if status == 403
                    else "failed"
                    if terminal
                    else "pending",
                    unknown=ambiguous,
                    token=None,
                    lease_until=None,
                    next_attempt=time.time()
                    + max(retry_after, min(3600, 5 * 2 ** min(attempts, 10))),
                    error=f"Private message delivery failed ({status or 'network'}).",
                )
            )
            db.commit()
        logger.warning(
            "Private promotion notice %s could not be delivered (%s)",
            notice_id,
            status or "network",
        )


def dispatch_due(engine: Engine, discord: DiscordAPI) -> None:
    now = time.time()
    with Session(engine) as db:
        ids = list(
            db.scalars(
                select(PromotionDM.id)
                .where(
                    PromotionDM.state.in_(["pending", "sending"]),
                    PromotionDM.next_attempt <= now,
                    or_(PromotionDM.token.is_(None), PromotionDM.lease_until <= now),
                )
                .order_by(PromotionDM.next_attempt)
                .limit(20)
            )
        )
    for notice_id in ids:
        try:
            deliver(engine, discord, notice_id)
        except Exception:
            logger.exception("Could not process private promotion notice %s", notice_id)


def withdraw(
    engine: Engine, notice_id: str, user_id: str, channel_id: str, message_id: str
) -> str:
    """Only the intended recipient may relinquish a current, future seat."""
    from app.assignments.withdrawals import withdraw_seat

    with Session(engine) as db:
        notice = db.get(PromotionDM, notice_id)
        if (
            notice is None
            or notice.discord_id != user_id
            or notice.state != "sent"
            or notice.channel_id != channel_id
            or notice.message_id != message_id
        ):
            return "This private message cannot be used to change your seat."
        claimed = db.execute(
            update(Event)
            .where(
                Event.id == notice.event_id,
                Event.status == "assigned",
                Event.archived_at.is_(None),
                Event.starts_at > time.time(),
            )
            .values(status=Event.status)
            .returning(Event.id)
        ).scalar_one_or_none()
        if claimed is None:
            return "This event has started or is no longer accepting withdrawals."
        event = db.get(Event, notice.event_id)
        run = db.get(LotteryRun, notice.event_id)
        if event is None or run is None:
            return "This event is no longer available."
        if not withdraw_seat(db, event, run, user_id, event.channel_id or ""):
            return "You no longer have a seat at this event."
        db.commit()
        return (
            f"You have withdrawn from {clean(event.title)}. "
            "Your seat is now available to the next waitlisted player."
        )
