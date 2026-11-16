"""Player-controlled notification preferences within the notice's organization."""

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.models import Event, LotteryRun, PromotionDM
from app.players.player_profiles import for_event


def stop_notifications(
    engine: Engine, notice_id: str, user_id: str, channel_id: str, message_id: str
) -> str:
    with Session(engine) as db:
        notice = db.get(PromotionDM, notice_id)
        if (
            notice is None
            or notice.discord_id != user_id
            or notice.state != "sent"
            or notice.channel_id != channel_id
            or notice.message_id != message_id
        ):
            return "Something went wrong. Please contact the host for assistance."
        event = db.get(Event, notice.event_id)
        if event is None:
            return "This event is no longer available."
        scope = for_event(event)
        scope.lock(db)
        profile = scope.get(db, user_id)
        if profile is None:
            run = db.get(LotteryRun, event.id)
            name = (
                next(
                    (p["name"] for p in run.snapshot["players"] if p["id"] == user_id),
                    user_id,
                )
                if run
                else user_id
            )
            profile = scope.create(user_id, discord_name=name)
            db.add(profile)
        profile.seat_notifications = False
        db.commit()
        return (
            "Private seat notifications are now off for this organizer. "
            "Your seat is unchanged. The host can re-enable notifications "
            "in your player profile."
        )
