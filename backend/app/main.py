"""Application composition root; feature behavior lives in routers and services."""

from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.branding import load_branding
from app.config import Settings
from app.context import ApplicationContext
from app.discord.discord_api import DiscordAPI
from app.lifecycle import application_lifespan
from app.models import Event
from app.routes import (
    assignments,
    auth,
    cleanup,
    events,
    organizations,
    players,
    preferences,
    signups,
)
from app.settings.connection_settings import register_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    branding = load_branding(config.branding_config_file)
    engine = create_engine(config.database_url, pool_pre_ping=True)
    app = FastAPI(title=branding.name)
    context = ApplicationContext(app, config, engine)
    app.router.lifespan_context = application_lifespan(
        context, auto_migrate=settings is None
    )
    app.state.engine = engine
    app.state.discord = DiscordAPI(config)

    @app.get("/api/branding")
    def public_branding() -> dict[str, str | None]:
        return branding.model_dump()

    @app.get("/api/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/health/ready")
    def ready() -> dict[str, str]:
        try:
            with Session(engine) as db:
                db.execute(text("SELECT 1"))
                db.execute(select(Event.id).limit(1))
        except Exception:
            raise HTTPException(503, "Database is not ready.") from None
        return {"status": "ok"}

    @app.get("/api/setup")
    def setup() -> dict[str, bool]:
        return {"configured": config.configured}

    for feature in (
        auth,
        organizations,
        preferences,
        players,
        events,
        signups,
        assignments,
        cleanup,
    ):
        feature.register(context)
    register_settings(app, engine, config, context.authenticated, context.legacy_access)
    return app


app = create_app()
