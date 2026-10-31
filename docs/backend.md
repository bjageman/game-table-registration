# Backend

Python/FastAPI API with database-backed Discord login sessions, moderator authorization, event drafts, and guarded native poll publication. The placeholder UI does not call these endpoints. Recurring schedules, lottery/waitlists, closure reconciliation, and production deployment remain future work.

Keep existing credentials in the ignored root `.env`; `.env.example` lists required variables. Existing DISCORD_BOT_CLIENTID and DISCORD_BOT_CLIENTSECRET names are supported. Add DISCORD_BOT_TOKEN, DISCORD_GUILD_ID, DISCORD_CHANNEL_ID, and OWNER_DISCORD_ID. Optional MODERATOR_ROLE_IDS is a comma-separated list. Set PUBLIC_URL to the browser origin and register that origin plus `/api/auth/callback` in Discord's OAuth2 settings. Current code rechecks guild membership and owner/role authorization on authenticated requests.

Requires Python 3.12+ and uv. Run `uv sync --frozen`, `uv run alembic upgrade head`, then `uv run uvicorn app.main:app --app-dir backend --host 127.0.0.1`. Direct development defaults to an ignored SQLite local.db. Compose and CI use PostgreSQL.

For Docker, create `.env` only if it is missing, then run `docker compose up --build -d --wait`. This starts PostgreSQL, migrations, and the API on localhost:8000. Check `/api/health/ready`. Database data persists in a named volume. This is a local/test configuration. After the frontend PR merges, add `-f compose.yml -f compose.frontend.yml` to include the frontend on localhost:8080.

Checks: `uv run ruff check backend`, `uv run ruff format --check backend`, `uv run mypy backend/app`, `uv run pytest`, and `uv run alembic check`. CI also tests PostgreSQL, migration upgrades/downgrades, dependency vulnerabilities, and Compose startup. TEST_DATABASE_URL must point only to a disposable database: tests reset its schema.

No live Discord messages are sent by tests. Real Discord acceptance remains pending. Ambiguous publication errors produce needs_review; a crash can leave publishing. Neither state is automatically retried, preventing accidental duplicate posts. API recovery tooling is a follow-up. The initial API uses REST and does not require a Gateway bot process.
