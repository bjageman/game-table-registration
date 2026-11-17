"""Resolve independent player profiles within an organization or personal account."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Event,
    Organization,
    PlayerPairing,
    PlayerProfile,
    TableSignup,
    UserIdentity,
)
from app.settings.assignment_preferences import scope_key


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

    def pairings(self, db: Session) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for edge in db.scalars(
            select(PlayerPairing)
            .where(
                PlayerPairing.scope_key == self.key,
                PlayerPairing.guild_id == self.guild_id,
            )
            .order_by(PlayerPairing.player_id, PlayerPairing.preferred_id)
        ):
            result.setdefault(edge.player_id, []).append(edge.preferred_id)
            result.setdefault(edge.preferred_id, []).append(edge.player_id)
        return {pid: sorted(ids) for pid, ids in result.items()}


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
