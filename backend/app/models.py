from typing import Any

from sqlalchemy import JSON, Float, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class LoginState(Base):
    __tablename__ = "login_states"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires: Mapped[float] = mapped_column(Float)
    purpose: Mapped[str] = mapped_column(String(16), default="login")
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)


class Session(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32))
    guilds: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    username: Mapped[str] = mapped_column(String(100))
    csrf: Mapped[str] = mapped_column(String(100))
    expires: Mapped[float] = mapped_column(Float)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("series_id", "starts_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    public_share_token: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True
    )
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(300), default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    channel_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    starts_at: Mapped[float] = mapped_column(Float)
    duration_hours: Mapped[int]
    tables: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    created_by: Mapped[str] = mapped_column(String(32))
    organization_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    message_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    signup_deleted_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    closes_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    test_signups: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    archived_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    published_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    close_started_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_seed: Mapped[str | None] = mapped_column(String(64), nullable=True)
    close_guarantees: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    close_adjust_weights: Mapped[bool | None] = mapped_column(nullable=True)
    close_weights: Mapped[dict[str, float] | None] = mapped_column(JSON, nullable=True)
    close_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    answers: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    signup_mode: Mapped[str] = mapped_column(String(16), default="poll")
    reaction_checkpoint: Mapped[float | None] = mapped_column(Float, nullable=True)
    reaction_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    update_thread_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    thread_sync_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    signup_roster_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    signup_roster_checked_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    signup_roster_messages: Mapped[list[dict[str, str]] | None] = mapped_column(
        JSON, nullable=True
    )
    series_id: Mapped[str | None] = mapped_column(
        ForeignKey("recurring_series.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    scheduled_publish_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class RecurringSeries(Base):
    __tablename__ = "recurring_series"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_by: Mapped[str] = mapped_column(String(32))
    organization_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    guild_id: Mapped[str] = mapped_column(String(32))
    channel_id: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(300), default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    tables: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    first_local: Mapped[str] = mapped_column(String(16))
    time_zone: Mapped[str] = mapped_column(String(100))
    frequency: Mapped[str] = mapped_column(String(16))
    opens_before_hours: Mapped[int]
    closes_before_hours: Mapped[int]
    active: Mapped[bool] = mapped_column(default=True)


class CanceledOccurrence(Base):
    __tablename__ = "canceled_occurrences"
    series_id: Mapped[str] = mapped_column(
        ForeignKey("recurring_series.id", ondelete="CASCADE"), primary_key=True
    )
    starts_at: Mapped[float] = mapped_column(Float, primary_key=True)


class EventTemplate(Base):
    __tablename__ = "event_templates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(300), default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    duration_hours: Mapped[int]
    tables: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float)


class TableSignup(Base):
    __tablename__ = "table_signups"
    event_id: Mapped[str] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    discord_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    discord_name: Mapped[str] = mapped_column(String(100))
    choices: Mapped[list[str]] = mapped_column(JSON)


class EventManagerSignup(Base):
    __tablename__ = "event_manager_signups"
    event_id: Mapped[str] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    discord_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    discord_name: Mapped[str] = mapped_column(String(100))
    choices: Mapped[list[str]] = mapped_column(JSON, default=list)
    removed: Mapped[bool] = mapped_column(default=False)


class EventPlayerSetting(Base):
    __tablename__ = "event_player_settings"
    event_id: Mapped[str] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    discord_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    weighting: Mapped[float | None] = mapped_column(Float, nullable=True)
    guaranteed_table: Mapped[str | None] = mapped_column(String(35), nullable=True)


class SignupInteraction(Base):
    __tablename__ = "signup_interactions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), index=True
    )
    response: Mapped[dict[str, Any]] = mapped_column(JSON)


class PlayerProfile(Base):
    __tablename__ = "player_profiles"
    guild_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    discord_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    discord_name: Mapped[str] = mapped_column(String(100), default="")
    guaranteed_seat: Mapped[bool] = mapped_column(default=False)
    is_test: Mapped[bool] = mapped_column(default=False)
    real_name: Mapped[str] = mapped_column(String(100), default="")
    weighting: Mapped[float] = mapped_column(Float, default=5.0)


class UserSettings(Base):
    __tablename__ = "user_settings"
    disconnected: Mapped[bool] = mapped_column(default=False)
    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32))
    guild_name: Mapped[str] = mapped_column(String(100))
    channel_id: Mapped[str] = mapped_column(String(32))
    channel_name: Mapped[str] = mapped_column(String(100))


class UserIdentity(Base):
    __tablename__ = "user_identities"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    username: Mapped[str] = mapped_column(String(100))


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    normalized_name: Mapped[str] = mapped_column(String(100), unique=True)
    created_by: Mapped[str] = mapped_column(String(32))
    guild_id: Mapped[str] = mapped_column(String(32))
    channel_id: Mapped[str] = mapped_column(String(32))


class OrganizationMember(Base):
    __tablename__ = "organization_members"
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    role: Mapped[str] = mapped_column(String(16))


class OrganizationSelection(Base):
    __tablename__ = "organization_selections"
    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )


class LotteryRun(Base):
    __tablename__ = "lottery_runs"
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), primary_key=True)
    version: Mapped[str] = mapped_column(String(64))
    seed: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[float] = mapped_column(Float)


class EventWithdrawal(Base):
    __tablename__ = "event_withdrawals"
    event_id: Mapped[str] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    discord_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    table_name: Mapped[str] = mapped_column(String(35))
    withdrawn_at: Mapped[float] = mapped_column(Float)
    promoted_id: Mapped[str | None] = mapped_column(String(32), nullable=True)


class EventManualAssignment(Base):
    __tablename__ = "event_manual_assignments"
    event_id: Mapped[str] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    discord_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    table_name: Mapped[str] = mapped_column(String(35))
    assigned_at: Mapped[float] = mapped_column(Float)


class Announcement(Base):
    __tablename__ = "announcements"
    __table_args__ = (
        UniqueConstraint("event_id", "part"),
        Index("ix_announcement_due", "state", "next_attempt"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"))
    part: Mapped[int]
    kind: Mapped[str] = mapped_column(
        String(16), default="assignment", server_default="assignment"
    )
    channel_id: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[float] = mapped_column(Float)
    next_attempt: Mapped[float] = mapped_column(Float)
    attempted_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    unknown: Mapped[bool] = mapped_column(default=False)
    token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_until: Mapped[float | None] = mapped_column(Float, nullable=True)
    message_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    deleted_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)


class GuildSettings(Base):
    __tablename__ = "guild_settings"
    guild_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    automatic_weight_adjustment: Mapped[bool] = mapped_column(default=True)


class AssignmentPreference(Base):
    __tablename__ = "assignment_preferences"
    scope_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    automatic_weight_adjustment: Mapped[bool] = mapped_column(default=True)
    announce_table_changes: Mapped[bool] = mapped_column(default=False)
    post_discord_updates_to_thread: Mapped[bool] = mapped_column(default=False)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    show_open_signup_players: Mapped[bool] = mapped_column(default=False)


class EventThreadMember(Base):
    __tablename__ = "event_thread_members"
    event_id: Mapped[str] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    discord_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    added_at: Mapped[float | None] = mapped_column(Float, nullable=True)
