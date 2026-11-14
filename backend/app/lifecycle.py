"""API lifespan and background synchronization worker."""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from functools import partial
from threading import Event as StopEvent
from threading import Thread
from typing import Any

from fastapi import FastAPI, HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session as DBSession

from app.announcements import (
    dispatch_due,
)
from app.closing import close_and_assign
from app.context import ApplicationContext
from app.event_threads import synchronize_due as synchronize_threads
from app.gateway import SignupGateway
from app.models import (
    Event,
    RecurringSeries,
)
from app.open_signup_rosters import synchronize_due as synchronize_open_rosters
from app.promotion_dms import dispatch_due as dispatch_promotion_dms
from app.publication import mark_signup_closed
from app.publication import publish_event as publish_event_service
from app.recurrence import fill_schedule
from app.signup_warnings import enqueue_due as enqueue_signup_warnings


def application_lifespan(
    context: ApplicationContext, auto_migrate: bool
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    config = context.config
    engine = context.engine
    client_for = context.client_for
    publish_event = partial(publish_event_service, context)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        # Direct local API starts (outside run.sh) must also upgrade SQLite
        # before background workers issue queries against the current models.
        # Hosted PostgreSQL deployments continue to run migrations separately.
        if auto_migrate and config.database_url.startswith("sqlite:"):
            from alembic import command
            from alembic.config import Config

            migration_config = Config("alembic.ini")
            migration_config.set_main_option("sqlalchemy.url", config.database_url)
            command.upgrade(migration_config, "head")

        stop = StopEvent()
        gateway = (
            SignupGateway(engine, config)
            if config.discord_gateway_enabled and config.configured
            else None
        )
        application.state.gateway = gateway
        gateway_task = asyncio.create_task(gateway.run_listener()) if gateway else None

        def work() -> None:
            while not stop.is_set():
                try:
                    with DBSession(engine) as db:
                        for series in db.scalars(
                            select(RecurringSeries).where(RecurringSeries.active)
                        ):
                            fill_schedule(db, series, time.time())
                        db.commit()
                        scheduled = [
                            (event.id, event.guild_id, event.channel_id)
                            for event in db.scalars(
                                select(Event)
                                .where(
                                    Event.status == "scheduled",
                                    Event.scheduled_publish_at <= time.time(),
                                )
                                .limit(50)
                            )
                        ]
                    for event_id, guild, channel in scheduled:
                        try:
                            if (
                                config.discord_signup_mode == "custom"
                                and config.discord_gateway_enabled
                            ):
                                if gateway is None or not gateway.is_ready():
                                    continue
                            target = config.model_copy(
                                update={
                                    "discord_guild_id": guild,
                                    "discord_channel_id": channel,
                                }
                            )
                            publish_event(event_id, client_for(target), "scheduled")
                            with DBSession(engine) as archive_db:
                                current = archive_db.get(Event, event_id)
                                if current and current.series_id:
                                    archive_db.execute(
                                        update(Event)
                                        .where(
                                            Event.series_id == current.series_id,
                                            Event.starts_at < current.starts_at,
                                            Event.status == "assigned",
                                            Event.archived_at.is_(None),
                                        )
                                        .values(archived_at=time.time())
                                    )
                                    archive_db.commit()
                        except HTTPException as error:
                            logging.getLogger(__name__).warning(
                                "Scheduled publication for %s: %s",
                                event_id,
                                error.detail,
                            )
                        except Exception:
                            logging.getLogger(__name__).exception(
                                "Scheduled publication failed for %s", event_id
                            )
                    # Close expired signups from durable event state. This also
                    # retries events left in `closing` after Discord was still
                    # finalizing a poll or reaction synchronization.
                    with DBSession(engine) as db:
                        due: list[dict[str, Any]] = [
                            {
                                "id": event.id,
                                "guild": event.guild_id,
                                "channel": event.channel_id,
                                "message": event.message_id,
                                "mode": event.signup_mode,
                                "deleted": event.signup_deleted_at,
                            }
                            for event in db.scalars(
                                select(Event)
                                .where(
                                    Event.status.in_(["open", "closing"]),
                                    Event.closes_at.is_not(None),
                                    Event.closes_at <= time.time(),
                                    Event.message_id.is_not(None),
                                    Event.channel_id.is_not(None),
                                )
                                .limit(50)
                            )
                        ]
                    for event in due:
                        target = config.model_copy(
                            update={
                                "discord_guild_id": event["guild"],
                                "discord_channel_id": event["channel"],
                            }
                        )
                        discord = client_for(target)
                        try:
                            complete = close_and_assign(
                                engine,
                                discord,
                                event["id"],
                                "system:auto",
                                event["channel"],
                            )
                            if complete and event["message"] and not event["deleted"]:
                                mark_signup_closed(
                                    discord, event["message"], event["mode"]
                                )
                        except Exception:
                            logging.getLogger(__name__).exception(
                                "Automatic signup closing failed for event %s",
                                event["id"],
                            )
                    synchronize_open_rosters(
                        engine,
                        context.client_for_destination,
                    )
                    synchronize_threads(
                        engine,
                        context.client_for_destination,
                    )
                    enqueue_signup_warnings(engine)
                    dispatch_due(
                        engine,
                        context.client_for_destination,
                    )
                    dispatch_promotion_dms(engine, context.app.state.discord)
                except Exception:
                    logging.getLogger(__name__).exception(
                        "Assignment delivery worker failed"
                    )
                stop.wait(5)

        worker = Thread(target=work, daemon=True)
        if config.announcement_worker_enabled:
            worker.start()
        try:
            yield
        finally:
            stop.set()
            if gateway:
                await gateway.close()
            if gateway_task:
                gateway_task.cancel()
                await asyncio.gather(gateway_task, return_exceptions=True)
            if worker.is_alive():
                await asyncio.to_thread(worker.join, 20)

    return lifespan
