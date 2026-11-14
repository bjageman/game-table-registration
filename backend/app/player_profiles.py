"""Resolve independent player profiles within an organization or personal account."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.assignment_preferences import scope_key
from app.models import Event, Organization, PlayerProfile, UserIdentity


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
