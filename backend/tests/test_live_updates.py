"""Commit and cleanup guarantees for data-free live invalidations."""

import asyncio

from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session

from app.live_updates import LiveUpdates
from app.models import Announcement, Event


def test_commits_bulk_updates_rollback_and_cleanup(promotion_db):
    hub = LiveUpdates(promotion_db)
    hub.start()

    async def check():
        stream = hub.stream()
        assert "event: ready" in await anext(stream)
        with Session(promotion_db) as db:
            row = db.get(Event, "event")
            row.title = "Updated title"
            db.commit()
        assert await asyncio.wait_for(anext(stream), 2) == "event: change\ndata: {}\n\n"
        with Session(promotion_db) as db:
            db.execute(update(Event).where(Event.id == "event").values(title="Bulk"))
            db.commit()
        assert "event: change" in await asyncio.wait_for(anext(stream), 2)

        with Session(promotion_db) as db:
            row = db.get(Event, "event")
            row.title = "Rolled back"
            db.flush()
            db.rollback()
        # No-op assignments made by roster reads must not create refresh loops.
        with Session(promotion_db) as db:
            row = db.get(Event, "event")
            row.title = row.title
            db.commit()
        await asyncio.sleep(0)
        assert all(queue.empty() for _, queue in hub.subscribers.values())
        await stream.aclose()
        assert not hub.subscribers

    try:
        asyncio.run(check())
    finally:
        hub.close()


def test_outbox_only_wakes_after_outer_commit(promotion_db):
    hub = LiveUpdates(promotion_db)
    hub.start()
    try:
        with Session(promotion_db) as db:
            with db.begin_nested():
                db.add(
                    Announcement(
                        id="queued",
                        event_id="event",
                        part=1,
                        state="pending",
                        channel_id="channel",
                        payload={"content": "Assignments"},
                        created_at=0,
                        next_attempt=0,
                    )
                )
                db.flush()
            assert not hub.worker_wake.is_set()
            db.commit()
        assert hub.worker_wake.is_set()
        hub.worker_wake.clear()
        with Session(promotion_db) as db:
            db.add(
                Announcement(
                    id="rollback",
                    event_id="event",
                    part=2,
                    state="pending",
                    channel_id="channel",
                    payload={},
                    created_at=0,
                    next_attempt=0,
                )
            )
            db.flush()
            db.rollback()
        assert not hub.worker_wake.is_set()
        other = create_engine("sqlite://")
        with Session(other) as db:
            db.info["live_changed"] = True
            db.commit()
            assert db.info["live_changed"] is True
        other.dispose()
    finally:
        hub.close()


def test_stream_routes_require_access(client):
    assert client.get("/api/live").status_code == 401
    assert client.get("/api/public/live/missing").status_code == 404


def test_postgres_updates_reach_other_workers(promotion_db):
    import pytest

    if promotion_db.dialect.name != "postgresql":
        pytest.skip("PostgreSQL LISTEN/NOTIFY coverage runs in CI")
    other_engine = create_engine(promotion_db.url)
    sender, receiver = LiveUpdates(promotion_db), LiveUpdates(other_engine)
    sender.start()
    receiver.start()

    async def check():
        assert await asyncio.to_thread(receiver.listener_ready.wait, 5)
        stream = receiver.stream()
        await anext(stream)
        with Session(promotion_db) as db:
            db.execute(
                update(Event).where(Event.id == "event").values(title="Other worker")
            )
            db.commit()
        assert "event: change" in await asyncio.wait_for(anext(stream), 5)
        assert receiver.worker_wake.is_set()
        await stream.aclose()

    try:
        asyncio.run(check())
    finally:
        sender.close()
        receiver.close()
        other_engine.dispose()


def test_authenticated_stream_invalidates_and_stops_after_session_expiry(client):
    from fastapi import Request
    from flow_helpers import login
    from sqlalchemy import delete

    from app.models import Session as LoginSession

    login(client)
    route = next(
        route
        for route in client.app.routes
        if getattr(route, "path", "") == "/api/live"
    )

    async def check():
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/live",
                "headers": [
                    (b"cookie", f"session={client.cookies.get('session')}".encode())
                ],
            }
        )
        response = await route.endpoint(request)
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-accel-buffering"] == "no"

        # The HTTP disconnect check needs an ASGI receiver. The generator is
        # consumed directly here to avoid TestClient buffering infinite streams.
        async def connected():
            return False

        request.is_disconnected = connected
        stream = response.body_iterator
        assert "event: ready" in await anext(stream)
        client.app.state.live_updates.publish()
        assert await asyncio.wait_for(anext(stream), 2) == "event: change\ndata: {}\n\n"
        with Session(client.app.state.engine) as db:
            db.execute(delete(LoginSession))
            db.commit()
        assert "event: access-revoked" in await asyncio.wait_for(anext(stream), 2)
        await stream.aclose()
        assert not client.app.state.live_updates.subscribers

    asyncio.run(check())


def test_poll_vote_add_and_remove_invalidate_live_rosters(promotion_db):
    from types import SimpleNamespace

    from app.config import Settings
    from app.discord.gateway import SignupGateway

    with Session(promotion_db) as db:
        row = db.get(Event, "event")
        row.status = "open"
        row.signup_mode = "poll"
        db.commit()
    hub = LiveUpdates(promotion_db)
    hub.start()

    async def check():
        gateway = SignupGateway(promotion_db, Settings(_env_file=None))
        stream = hub.stream()
        await anext(stream)
        vote = SimpleNamespace(
            guild_id="guild", channel_id="channel", message_id="signup", user_id=123
        )
        try:
            for handler in [
                gateway.on_raw_poll_vote_add,
                gateway.on_raw_poll_vote_remove,
            ]:
                await handler(vote)
                assert "event: change" in await asyncio.wait_for(anext(stream), 2)
            vote.message_id = "unrelated"
            await gateway.on_raw_poll_vote_remove(vote)
            await asyncio.sleep(0)
            assert all(queue.empty() for _, queue in hub.subscribers.values())
        finally:
            await stream.aclose()
            await gateway.close()

    try:
        asyncio.run(check())
    finally:
        hub.close()


def test_shared_lifespans_keep_notifications_until_last_close(promotion_db):
    hub = LiveUpdates(promotion_db)
    hub.start()
    first_listener = hub.listener
    hub.start()
    assert hub.listener is first_listener
    hub.close()
    assert not hub.stop.is_set()

    async def check():
        stream = hub.stream()
        await anext(stream)
        with Session(promotion_db) as db:
            db.execute(
                update(Event).where(Event.id == "event").values(title="Still live")
            )
            db.commit()
        assert "event: change" in await asyncio.wait_for(anext(stream), 2)
        await stream.aclose()

    try:
        asyncio.run(check())
    finally:
        hub.close()
    assert hub.stop.is_set()
    hub.close()  # Repeated cleanup is harmless.
    hub.start()  # The same app can start again after complete shutdown.
    try:
        assert not hub.stop.is_set()
        asyncio.run(check())
    finally:
        hub.close()
