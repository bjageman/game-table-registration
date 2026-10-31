# Backend

Python/FastAPI API with database-backed Discord login sessions, moderator authorization, event drafts, and guarded native poll publication.

Keep credentials in the ignored root `.env`; `.env.example` lists required variables. Use DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET for the application's OAuth2 credentials. Also set DISCORD_BOT_TOKEN, DISCORD_GUILD_ID (the Discord server ID), DISCORD_CHANNEL_ID, and OWNER_DISCORD_ID. Optional MODERATOR_ROLE_IDS is a comma-separated list. Set PUBLIC_URL to the browser origin and register that origin plus `/api/auth/callback` in Discord's OAuth2 settings. The API rechecks guild membership and owner/role authorization on authenticated requests.

Requires Python 3.12+ and uv. Run `uv sync --frozen`, `uv run alembic upgrade head`, then `uv run uvicorn app.main:app --app-dir backend --host 127.0.0.1`. Direct development defaults to an ignored SQLite local.db. Compose and CI use PostgreSQL.

For Docker, create `.env` only if it is missing, then run `docker compose up --build -d --wait`. This starts PostgreSQL, migrations, and the API on localhost:8000. Check `/api/health/ready`. Database data persists in a named volume. This is a local/test configuration.

Checks: `uv run ruff check backend`, `uv run ruff format --check backend`, `uv run mypy backend/app`, `uv run pytest`, and `uv run alembic check`. CI also tests PostgreSQL, migration upgrades/downgrades, dependency vulnerabilities, and Compose startup. TEST_DATABASE_URL must point only to a disposable database: tests reset its schema.

Tests mock Discord requests and do not send live messages. Ambiguous publication errors produce `needs_review`; a crash can leave `publishing`. Neither state is automatically retried, preventing accidental duplicate posts. Check Discord before recovering an event in either state. The API uses REST and does not require a Gateway bot process.

Scheduled signups use explicit UTC opening/closing timestamps and a saved IANA timezone. Confirm Schedule signups to activate a draft. Run `python -m app.worker` with `PYTHONPATH=backend` alongside the API (Compose includes the worker). Database states act as durable jobs; workers atomically claim publication and closing operations. Interrupted operations and missed custom closing deadlines require moderator review. Native expiry rounds up to whole hours; closed means the deadline operation completed, not that voters have been reconciled or assigned.

Weekly schedules store local wall-clock rules in an IANA timezone and materialize eight upcoming event dates. The preview rejects ambiguous/nonexistent local times and inverted windows; a moderator may explicitly skip such dates. Occurrences have a unique schedule/date key and independent table snapshots. The worker replenishes active schedules and surfaces blocked future dates on the schedule rather than guessing a DST offset.

Future schedule edits require the current revision and preview affected dates. Published/claimed occurrences and individual overrides retain their snapshots. Skips and cancellations persist as occurrence tombstones so replenishment cannot recreate them. Pausing stops unpublished openings while open polls retain closing jobs; resuming holds expired windows for review. Cancellation of an open poll claims the event before contacting Discord and holds uncertain results for review.
