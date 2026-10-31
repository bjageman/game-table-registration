from typing import Any

from sqlalchemy import JSON, Float, Index, String
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
    username: Mapped[str] = mapped_column(String(100))
    csrf: Mapped[str] = mapped_column(String(100))
    expires: Mapped[float] = mapped_column(Float)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("uq_event_occurrence", "schedule_id", "occurrence_date", unique=True),
    )
    schedule_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    occurrence_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    overridden: Mapped[bool] = mapped_column(default=False)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(100))
    starts_at: Mapped[float] = mapped_column(Float)
    timezone: Mapped[str] = mapped_column(String(100), default="UTC")
    opens_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    signup_closes_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_hours: Mapped[int]
    tables: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    created_by: Mapped[str] = mapped_column(String(32))
    message_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    closes_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    voter_snapshot: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True
    )
    reconciled_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    reconciliation_attempts: Mapped[int] = mapped_column(default=0)
    reconcile_after: Mapped[float | None] = mapped_column(Float, nullable=True)
    recovery_audit: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    operation_started_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    answers: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)


class Schedule(Base):
    __tablename__ = "schedules"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(100))
    timezone: Mapped[str] = mapped_column(String(100))
    rule: Mapped[dict[str, Any]] = mapped_column(JSON)
    tables: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(default=True)
    revision: Mapped[int] = mapped_column(default=1)
    created_by: Mapped[str] = mapped_column(String(32))
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)


class Withdrawal(Base):
    __tablename__ = "withdrawals"
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    created_at: Mapped[float] = mapped_column(Float)


class LiveVote(Base):
    __tablename__ = "live_votes"
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    answer_id: Mapped[int] = mapped_column(primary_key=True)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    last_seen: Mapped[float] = mapped_column(Float)
