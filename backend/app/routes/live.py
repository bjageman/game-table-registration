"""Authenticated invalidation streams with heartbeat access checks."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import aclosing

from fastapi import HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.context import ApplicationContext
from app.live_updates import LiveUpdates
from app.models import Event


def register(context: ApplicationContext) -> None:
    hub: LiveUpdates = context.app.state.live_updates

    @context.app.middleware("http")
    async def wake_on_mutation(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        result = await call_next(request)
        if (
            request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and result.status_code < 400
        ):
            hub.worker_wake.set()
        return result

    async def response(request: Request, token: str | None = None) -> StreamingResponse:
        def authorize() -> None:
            if token is None:
                context.authenticated(request, require_destination=False)
            else:
                with Session(context.engine) as db:
                    shared = db.scalar(
                        select(Event.id).where(
                            Event.public_share_token == token,
                            Event.status == "assigned",
                        )
                    )
                    if shared is None:
                        raise HTTPException(404, "Shared event not found")

        await asyncio.to_thread(authorize)

        async def stream() -> AsyncIterator[str]:
            async with aclosing(hub.stream()) as updates:
                async for message in updates:
                    if await request.is_disconnected():
                        return
                    try:
                        await asyncio.to_thread(authorize)
                    except HTTPException:
                        yield "event: access-revoked\ndata: {}\n\n"
                        return
                    yield message

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-store",
                "X-Accel-Buffering": "no",
            },
        )

    @context.app.get("/api/live")
    async def live(request: Request) -> StreamingResponse:
        return await response(request)

    @context.app.get("/api/public/live/{token}")
    async def public_live(token: str, request: Request) -> StreamingResponse:
        return await response(request, token)
