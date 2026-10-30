# Gather · Game table registration

Discord signup polls and a moderator dashboard for in-person games. Built with Python/FastAPI, SQLAlchemy, PostgreSQL, and React/TypeScript/Vite/Tailwind.

## First milestone

Discord moderator login → create an event draft → publish one native multi-answer poll with up to 10 tables. Per-table capacity defaults to 15. Publication opens signups immediately for a whole-number duration in hours. Saved drafts and published message/answer IDs survive restarts.

**Early preview:** recurring schedules, editing drafts, voter reconciliation, lottery allocation, waitlists, and notifications are not implemented yet. Discord closes the poll itself at expiry; the dashboard does not yet transition expired polls to a closed status. Test in a private test server, not a real signup event.

## Discord configuration

Keep your existing `.env`; add missing values using `.env.example` as a reference. Never copy over your credentials. The existing `DISCORD_BOT_CLIENTID` and `DISCORD_BOT_CLIENTSECRET` names are supported. `DISCORD_BOT_TOKEN` comes from Developer Portal → Bot, not the client secret or public key.

Set `DISCORD_GUILD_ID`, `DISCORD_CHANNEL_ID`, and `OWNER_DISCORD_ID`. Enable Developer Mode in Discord to copy these IDs from context menus. Optional `MODERATOR_ROLE_IDS` is a comma-separated list of role IDs. Every authenticated API operation checks current server membership and owner/role authorization through Discord; lookup failures deny access.

Install the bot with `bot` and `applications.commands` scopes and View Channels, Send Messages, Embed Links, Read Message History, and Send Polls permissions. Configure the OAuth redirect URI in Developer Portal → OAuth2:

- Direct local development: `http://localhost:5180/api/auth/callback`
- Local Compose: `http://localhost:8080/api/auth/callback`

The redirect must match `PUBLIC_URL` exactly. Use `localhost`, not `127.0.0.1`, in your browser. Production will require HTTPS. The initial implementation sends polls using Discord's REST API; a Gateway bot process is not needed yet and the bot may appear offline.

## Run directly without Docker

Requires Python 3.12+, uv, and Node 22.12+ (CI uses Node 24).

```sh
uv sync --frozen
uv run alembic upgrade head
uv run uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1
```

In another terminal:

```sh
cd frontend
npm ci
npm run dev
```

Open http://localhost:5180. The direct-development default uses an ignored SQLite database (`local.db`); PostgreSQL is used by Compose and CI. Set `DATABASE_URL` to use PostgreSQL directly. The API must be restarted after `.env` changes. Schema changes require Alembic migrations; the API does not create tables at startup.

## Run with Compose

Requires Docker with the Compose plugin. Create `.env` from the example only if you do not already have one.

```sh
docker compose up --build -d --wait
```

Open http://localhost:8080. Compose runs PostgreSQL, a one-shot migration, the API, and the frontend proxy. The web port binds only to localhost. Database storage persists in a named volume. This is a local/test configuration; production proxy integration, image promotion, backups, and deployment workflows remain in issue #7. `docker-compose.example.yml` is the original hosting reference, not the runnable application configuration.

## Checks

```sh
uv run ruff check backend
uv run ruff format --check backend
uv run mypy backend/app
uv run pytest
uv run alembic check
cd frontend
npm run lint
npm run build
npm test
npx playwright install chromium
npm run test:e2e
```

Backend tests use a temporary SQLite database by default. CI sets `TEST_DATABASE_URL` to a disposable PostgreSQL database; **never point this variable at real data**, because tests reset its schema. CI checks migrations, lint/types, backend tests, frontend build/tests, desktop/mobile browser flows, dependency audits, and Compose health. Browser tests mock Discord; real OAuth and poll publication require the dev-guild acceptance check below.

## Dev-guild acceptance

1. Configure `.env` and the OAuth redirect, then start both services.
2. Sign in as the configured owner. Verify an unrelated Discord user is denied.
3. Create a future event with two tables and a one-hour signup duration. Review the draft.
4. Publish once. Confirm exactly one multi-select poll appears in the configured channel, capacities are correct, and the dashboard links to that poll.
5. Restart the API and confirm the event remains and cannot be published twice. Sign out.

An ambiguous network failure leaves the event in `needs_review`; a process crash while sending can leave `publishing`. Neither is automatically retried. Check Discord before repairing the record; administrative reconciliation tools are a later milestone. No live Discord messages are sent by automated tests.

## Review workflow

Feature branches → PRs targeting `dev` → human review and merge. Agents never merge, enable auto-merge, or push directly to `dev`/`main`. The owner controls production promotion. See [AGENTS.md](AGENTS.md).

See the [development plan](docs/development-plan.md) and [issues](https://github.com/bjageman/game-table-registration/issues) for remaining work.
