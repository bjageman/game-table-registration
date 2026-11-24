"""Attendance writes authorized by possession of an opt-in public share link."""

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.assignments.roster import build_current_roster
from app.context import ApplicationContext
from app.models import Event, LotteryRun
from app.public_checklist import public_player_id

PlayerKey = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class CheckmarkInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    player_id: PlayerKey
    arrived: StrictBool


class ReplaceChecklistInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    entries: dict[PlayerKey, StrictBool] = Field(max_length=10000)


def shared_event(db: Session, token: str) -> tuple[Event, set[str]]:
    event = db.scalar(select(Event).where(Event.public_share_token == token))
    if event is None or event.status != "assigned":
        raise HTTPException(404, "Shared event not found")
    run = db.get(LotteryRun, event.id)
    if run is None:
        raise HTTPException(404, "Shared event not found")
    ids = {
        public_player_id(token, str(player["id"]))
        for table in build_current_roster(db, run)["tables"]
        for key in ("players", "waitlist")
        for player in table.get(key, [])
    }
    return event, ids


def snapshot(event: Event, ids: set[str]) -> dict[str, Any]:
    return {
        "revision": event.public_checklist_revision,
        "entries": {key: event.public_checklist.get(key, False) for key in sorted(ids)},
    }


def register(context: ApplicationContext) -> None:
    router = APIRouter(prefix="/api/public/events/{token}/checklist")

    @router.get("")
    def read_checklist(token: str, response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        with Session(context.engine) as db:
            event, ids = shared_event(db, token)
            return snapshot(event, ids)

    @router.patch("")
    def check_player(
        token: str, body: CheckmarkInput, response: Response
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        # Merge one player's edit against the latest revision. Different players'
        # simultaneous check-ins must not overwrite each other.
        for _ in range(5):
            with Session(context.engine) as db:
                event, ids = shared_event(db, token)
                if body.player_id not in ids:
                    raise HTTPException(422, "Player is no longer in this roster")
                entries = {**event.public_checklist, body.player_id: body.arrived}
                changed = db.execute(
                    update(Event)
                    .where(
                        Event.id == event.id,
                        Event.status == "assigned",
                        Event.public_share_token == token,
                        Event.public_checklist_revision
                        == event.public_checklist_revision,
                    )
                    .values(
                        public_checklist=entries,
                        public_checklist_revision=event.public_checklist_revision + 1,
                    )
                    .returning(Event.id)
                ).scalar_one_or_none()
                if changed:
                    db.commit()
                    db.refresh(event)
                    return snapshot(event, ids)
        raise HTTPException(409, "Checklist changed. Refresh and try again.")

    @router.put("")
    def replace_checklist(
        token: str, body: ReplaceChecklistInput, response: Response
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        with Session(context.engine) as db:
            event, ids = shared_event(db, token)
            if not body.entries.keys() <= ids:
                raise HTTPException(422, "Player is no longer in this roster")
            changed = db.execute(
                update(Event)
                .where(
                    Event.id == event.id,
                    Event.status == "assigned",
                    Event.public_share_token == token,
                    Event.public_checklist_revision == body.revision,
                )
                .values(
                    public_checklist={
                        key: value for key, value in body.entries.items() if value
                    },
                    public_checklist_revision=body.revision + 1,
                )
                .returning(Event.id)
            ).scalar_one_or_none()
            if not changed:
                raise HTTPException(
                    409,
                    "Server checklist changed. "
                    "Compare the latest versions before replacing it.",
                )
            db.commit()
            db.refresh(event)
            return snapshot(event, ids)

    context.app.include_router(router)
