from typing import Any

from sqlalchemy import JSON, Float, String
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
    answers: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
