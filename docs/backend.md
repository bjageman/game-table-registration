# Backend

Python/FastAPI API with database-backed Discord login sessions, moderator authorization, event drafts, and guarded native poll publication.

Keep the shared application's DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, and DISCORD_BOT_TOKEN in the ignored root `.env`. Set PUBLIC_URL to the browser origin and register that origin plus `/api/auth/callback` in Discord's OAuth2 settings. Sign-in requests `identify guilds`; only manageable server IDs and names are retained in the session, not OAuth tokens. The bot must allow Public Bot and Guild Install for other users to install it.

Each user selects an active server and channel under Settings. The Discord install link requests View Channel, Send Messages, Read Message History, and Send Polls, without Administrator. Channel discovery and saves recheck server ownership/Manage Server and effective channel permissions for both the user and bot. Event and profile operations recheck current access; event queries/mutations are scoped to the selected server/channel. Events store their original channel independently of later settings changes. Profiles remain scoped to their server and survive event deletion.

DISCORD_GUILD_ID, DISCORD_CHANNEL_ID, OWNER_DISCORD_ID, and MODERATOR_ROLE_IDS remain optional legacy defaults. Existing events in that default server have their channel captured by the destinations migration; retain those env defaults through that migration. New users can authenticate without belonging to the legacy server and are directed to Settings. Shared bot credentials are never accepted or returned by the settings API.

Requires Python 3.12+ and uv. Run `uv sync --frozen`, `uv run alembic upgrade head`, then `uv run uvicorn app.main:app --app-dir backend --host 127.0.0.1`. Direct development defaults to an ignored SQLite local.db. Compose and CI use PostgreSQL.

For Docker, create `.env` only if it is missing, then run `docker compose up --build -d --wait`. This starts PostgreSQL, migrations, and the API on localhost:8000. Check `/api/health/ready`. Database data persists in a named volume. This is a local/test configuration.

Checks: `uv run ruff check backend`, `uv run ruff format --check backend`, `uv run mypy backend/app`, `uv run pytest`, and `uv run alembic check`. CI also tests PostgreSQL, migration upgrades/downgrades, dependency vulnerabilities, and Compose startup. TEST_DATABASE_URL must point only to a disposable database: tests reset its schema.

Tests mock Discord requests and do not send live messages. Ambiguous publication errors produce `needs_review`; a crash can leave `publishing`. Neither state is automatically retried, preventing accidental duplicate posts. Check Discord before recovering an event in either state. The API uses REST and does not require a Gateway bot process.

Manual assignment: POST `/api/events/{id}/close` requires moderator access, the selected server/channel, and CSRF. The open → closing → assigned transition uses a two-minute claim lease. Closing freezes a secure seed and guild profile weights once, ends an unexpired Discord poll, waits for finalized result counts, and reconciles every paginated voter list before drawing. Incomplete/failing reads retain closing state without a lottery; retrying finishes with the same seed/weights. An interrupted claim can be recovered after its lease expires. Already-assigned requests return the saved event and never redraw.

The `weighted-matching-v1` engine sorts players by `-ln(U)/weight` using reproducible independent hash draws from the recorded seed. Capacity-aware augmenting paths may move earlier accepted players between their selected tables but cannot evict them. The event has one immutable lottery run containing the algorithm version, seed, input snapshot, complete placements, and original-order shared waitlist. GET `/api/events/{id}/assignments` exposes replay data to authorized moderators. The existing signups endpoint returns saved table placements/waitlists once assigned. This phase displays results in TableSignup; automatic promotions, withdrawals, scheduling, and Discord result notifications remain future work. No live Discord polls are changed in automated tests.
