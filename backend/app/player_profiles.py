"""Resolve independent player profiles within an organization or personal account."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.assignment_preferences import scope_key
from app.models import Event, Organization, PlayerProfile, TableSignup, UserIdentity


@dataclass(frozen=True)
class PlayerScope:
    key: str
    guild_id: str

    def lock(self, db: Session) -> None:
        """Serialize link changes even when the scope has no saved profiles yet."""
        if self.key.startswith("org:"):
            db.execute(
                update(Organization)
                .where(Organization.id == self.key[4:])
                .values(name=Organization.name)
            )
        else:
            db.execute(
                update(UserIdentity)
                .where(UserIdentity.id == self.key[5:])
                .values(username=UserIdentity.username)
            )

    def filters(self) -> tuple[Any, ...]:
        return (
            PlayerProfile.scope_key == self.key,
            PlayerProfile.guild_id == self.guild_id,
        )

    def get(self, db: Session, player_id: str) -> PlayerProfile | None:
        return db.get(PlayerProfile, (self.key, self.guild_id, player_id))

    def create(self, player_id: str, **values: Any) -> PlayerProfile:
        return PlayerProfile(
            scope_key=self.key, guild_id=self.guild_id, discord_id=player_id, **values
        )

    def pairs(self, db: Session) -> dict[str, str]:
        profiles = list(db.scalars(select(PlayerProfile).where(*self.filters())))
        linked = {p.discord_id: p.partner_id for p in profiles if p.partner_id}
        return {
            pid: partner
            for pid, partner in linked.items()
            if linked.get(partner) == pid
        }


def for_event(event: Event) -> PlayerScope:
    return PlayerScope(
        scope_key(event.organization_id, event.created_by), event.guild_id
    )


def remember_poll_players(
    db: Session, event: Event, rows: list[dict[str, Any]]
) -> None:
    """Remember discovered identities for search; Discord remains the vote source."""
    if event.status != "open" or event.signup_mode != "poll":
        return
    players = {p["id"]: p["name"] for row in rows for p in row["players"]}
    for pid, name in sorted(players.items()):
        saved = db.get(TableSignup, (event.id, pid))
        if saved:
            saved.discord_name = name[:100]
            continue
        try:
            with db.begin_nested():
                db.add(
                    TableSignup(
                        event_id=event.id,
                        discord_id=pid,
                        discord_name=name[:100],
                        choices=[],
                    )
                )
                db.flush()
        except IntegrityError:
            # Another roster refresh may have discovered this identity first.
            continue
