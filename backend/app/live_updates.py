"""Commit-driven live refresh signals; streams contain no application data."""

import asyncio
import logging
import socket
import threading
import uuid
from collections.abc import AsyncGenerator
from select import select
from typing import Any

import psycopg
from sqlalchemy import Engine, event, text
from sqlalchemy.orm import ORMExecuteState, Session

from app.models import Announcement, DiscordScheduledEvent, PromotionDM

logger = logging.getLogger(__name__)


def request_refresh(session: Session) -> None:
    """Signal external changes, such as Discord votes, after commit."""
    session.info["live_changed"] = True


class LiveUpdates:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.worker_wake = threading.Event()
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.subscribers: dict[
            str, tuple[asyncio.AbstractEventLoop, asyncio.Queue[None]]
        ] = {}
        self.identity = str(uuid.uuid4())
        self.listener: threading.Thread | None = None
        self.listener_ready = threading.Event()
        self.shutdown_read: socket.socket | None = None
        self.shutdown_write: socket.socket | None = None

    def publish(self) -> None:
        with self.lock:
            subscribers = list(self.subscribers.values())
        for loop, queue in subscribers:

            def push(target: asyncio.Queue[None] = queue) -> None:
                if target.empty():
                    target.put_nowait(None)

            try:
                loop.call_soon_threadsafe(push)
            except RuntimeError:
                pass  # The client disconnected while the commit completed.

    async def stream(self) -> AsyncGenerator[str, None]:
        key = str(uuid.uuid4())
        queue: asyncio.Queue[None] = asyncio.Queue(maxsize=1)
        with self.lock:
            self.subscribers[key] = (asyncio.get_running_loop(), queue)
        try:
            yield "retry: 1000\nevent: ready\ndata: {}\n\n"
            while not self.stop.is_set():
                try:
                    await asyncio.wait_for(queue.get(), timeout=15)
                    yield "event: change\ndata: {}\n\n"
                except TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            with self.lock:
                self.subscribers.pop(key, None)

    def owns(self, session: Session) -> bool:
        return session.bind is self.engine

    def before_flush(self, session: Session, context: Any, instances: Any) -> None:
        if self.owns(session) and (
            session.new
            or session.deleted
            or any(session.is_modified(row) for row in session.dirty)
        ):
            session.info["live_changed"] = True
            if any(
                isinstance(row, (Announcement, PromotionDM, DiscordScheduledEvent))
                for row in session.new
            ):
                session.info["wake_worker"] = True

    def executing(self, state: ORMExecuteState) -> None:
        if self.owns(state.session) and (
            state.is_update or state.is_delete or state.is_insert
        ):
            state.session.info["live_changed"] = True

    def committing(self, session: Session) -> None:
        if not self.owns(session) or session.in_nested_transaction():
            return
        if not (
            session.info.get("live_changed")
            or session.new
            or session.deleted
            or any(session.is_modified(row) for row in session.dirty)
        ):
            return
        session.info["live_changed"] = True
        if self.engine.dialect.name == "postgresql":
            # Use the existing transaction: NOTIFY is delivered only on commit,
            # without acquiring another pooled connection in after_commit.
            session.connection().execute(
                text("SELECT pg_notify('tablesignup_changed', :sender)"),
                {"sender": self.identity},
            )

    def committed(self, session: Session) -> None:
        if not self.owns(session) or session.in_nested_transaction():
            return
        if session.info.pop("wake_worker", False):
            self.worker_wake.set()
        if not session.info.pop("live_changed", False):
            return
        self.publish()

    def rolled_back(self, session: Session) -> None:
        if self.owns(session) and not session.in_nested_transaction():
            session.info.pop("live_changed", None)
            session.info.pop("wake_worker", None)

    def listen(self) -> None:
        shutdown = self.shutdown_read
        assert shutdown is not None
        url = self.engine.url.render_as_string(hide_password=False).replace(
            "postgresql+psycopg://", "postgresql://"
        )
        while not self.stop.is_set():
            try:
                with psycopg.connect(
                    url, autocommit=True, connect_timeout=5
                ) as connection:
                    connection.execute("LISTEN tablesignup_changed")
                    self.listener_ready.set()
                    while not self.stop.is_set():
                        readable, _, _ = select(
                            [connection.pgconn.socket, shutdown.fileno()], [], [], 5
                        )
                        if self.stop.is_set():
                            return
                        if connection.pgconn.socket not in readable:
                            continue
                        for notification in connection.notifies(timeout=0):
                            if notification.payload != self.identity:
                                self.publish()
                                self.worker_wake.set()
            except Exception:
                self.listener_ready.clear()
                logger.warning("Live notification listener disconnected; reconnecting")
                self.stop.wait(5)

    def start(self) -> None:
        self.stop.clear()
        event.listen(Session, "before_flush", self.before_flush)
        event.listen(Session, "do_orm_execute", self.executing)
        event.listen(Session, "before_commit", self.committing)
        event.listen(Session, "after_commit", self.committed)
        event.listen(Session, "after_rollback", self.rolled_back)
        if self.engine.dialect.name == "postgresql":
            self.listener_ready.clear()
            self.shutdown_read, self.shutdown_write = socket.socketpair()
            self.listener = threading.Thread(target=self.listen, daemon=True)
            self.listener.start()

    def close(self) -> None:
        self.stop.set()
        self.worker_wake.set()
        event.remove(Session, "before_flush", self.before_flush)
        event.remove(Session, "do_orm_execute", self.executing)
        event.remove(Session, "before_commit", self.committing)
        event.remove(Session, "after_commit", self.committed)
        event.remove(Session, "after_rollback", self.rolled_back)
        if self.shutdown_write:
            self.shutdown_write.send(b"stop")
        if self.listener:
            self.listener.join(timeout=6)
        if self.shutdown_read:
            self.shutdown_read.close()
        if self.shutdown_write:
            self.shutdown_write.close()
