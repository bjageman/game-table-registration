from typing import Any

from sqlalchemy import JSON, Float, ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class LoginState(Base):
    __tablename__ = "login_states"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires: Mapped[float] = mapped_column(Float)


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
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(100))
    channel_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    starts_at: Mapped[float] = mapped_column(Float)
    duration_hours: Mapped[int]
    tables: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    created_by: Mapped[str] = mapped_column(String(32))
    message_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    closes_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    published_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    close_started_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_seed: Mapped[str | None] = mapped_column(String(64), nullable=True)
    close_weights: Mapped[dict[str, float] | None] = mapped_column(JSON, nullable=True)
    close_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    answers: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)


class PlayerProfile(Base):
    __tablename__ = "player_profiles"
    guild_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    discord_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    discord_name: Mapped[str] = mapped_column(String(100), default="")
    real_name: Mapped[str] = mapped_column(String(100), default="")
    weighting: Mapped[float] = mapped_column(Float, default=1.0)


class UserSettings(Base):
    __tablename__ = "user_settings"
    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32))
    guild_name: Mapped[str] = mapped_column(String(100))
    channel_id: Mapped[str] = mapped_column(String(32))
    channel_name: Mapped[str] = mapped_column(String(100))


class LotteryRun(Base):
    __tablename__ = "lottery_runs"
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), primary_key=True)
    version: Mapped[str] = mapped_column(String(64))
    seed: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[float] = mapped_column(Float)
