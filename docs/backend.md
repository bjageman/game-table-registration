# Backend

Python/FastAPI API with database-backed Discord login sessions, moderator authorization, event drafts, and guarded Discord signup publication.

New publications default to custom Discord table signups (`DISCORD_SIGNUP_MODE=custom`). The API starts a `discord.py` Gateway listener using `DISCORD_BOT_TOKEN`, with automatic reconnect and graceful shutdown. Leave the application's **Interactions Endpoint URL blank** in Discord Developer Portal → General Information. The listener checks the application ID and refuses to run if a webhook endpoint is configured. No public key, inbound public endpoint, tunnel, port forwarding, or privileged intent is needed. Local browsers can continue using the LAN IP and existing OAuth callback. Publication is blocked before claiming the draft while the listener is disconnected; check API logs for startup/configuration errors. `DISCORD_SIGNUP_MODE=poll` explicitly retains native poll publication during rollout without changing existing events. Set `DISCORD_GATEWAY_ENABLED=false` only for isolated tests or API-only processes; at least one listener is required for real custom signups.

Run exactly one API/Gateway listener per Discord application: use one Uvicorn worker and one API replica. Do not run local and hosted instances of the same bot simultaneously; both may receive interactions and access different databases. Stop the other instance for local testing, or use a separate development application when production must stay running. The listener dispatches signup component IDs without relying on in-memory view registrations, so saved public buttons and private menus keep working after an app restart. It defers responses before database work, opens new menus privately, and updates only private app-owned menus; database failures return a private retry message. The previous HTTP interactions endpoint has been removed, and old `DISCORD_PUBLIC_KEY` environment entries are ignored.

New signup messages show each table beside a numbered emoji (1️⃣ through 🔟). The bot adds those reactions after publishing. Players can react to every table they would attend and remove a reaction to withdraw from that table; no menu or website visit is required. These are lottery entries, not reserved seats. Existing menu-based events and native polls keep their original behavior. Selections are saved by event and Discord user ID. Raw Gateway reaction events use the message's original server/channel and the event's deadline. The Gateway periodically checks for missed reactions after reconnecting and refreshes saved choices from Discord while signup is still open. A connection gap crossing the deadline is marked for review; closing is blocked rather than silently accepting a possibly incomplete snapshot. The organizer can publish a replacement event if a gap cannot be reconciled. Closing early updates the Discord message to say signups have ended; further reaction changes are ignored.

The custom-signups migration marks all existing events as `poll`; already-published polls retain their voter reconciliation and closing process. Existing drafts switch to the configured mode when published. Deleting an event removes its selections and interaction receipts while preserving player profiles. The existing `delete_poll=true` API parameter also deletes custom signup messages.

Keep the shared application's DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, and DISCORD_BOT_TOKEN in the ignored root `.env`. Set PUBLIC_URL to the browser origin and register that origin plus `/api/auth/callback` in Discord's OAuth2 settings. Sign-in requests `identify guilds`; only manageable server IDs and names are retained in the session, not OAuth tokens. The bot must allow Public Bot and Guild Install for other users to install it.

Each user selects an active server and channel under Settings. The Discord install link requests View Channel, Send Messages, Read Message History, and Add Reactions, without Administrator. Native poll publication mode additionally requests Send Polls. Channel discovery and saves recheck server ownership/Manage Server and effective channel permissions for both the user and bot. Event and profile operations recheck current access; event queries/mutations are scoped to the selected server/channel. Events store their original channel independently of later settings changes. Profiles are independent per organization or personal workspace, with guild/user keys inside that scope, and survive event deletion.

GET `/api/players` returns the selected organization or personal workspace's saved profiles and players present in signup or assignment history, sorted by saved display name or Discord name. It requires the same current moderator access as other profile operations.

DISCORD_GUILD_ID, DISCORD_CHANNEL_ID, OWNER_DISCORD_ID, and MODERATOR_ROLE_IDS remain optional legacy defaults. Existing events in that default server have their channel captured by the destinations migration; retain those env defaults through that migration. New users can authenticate without belonging to the legacy server and are directed to Settings. Shared bot credentials are never accepted or returned by the settings API.

Requires Python 3.12+ and uv. Run `uv sync --frozen`, `uv run alembic upgrade head`, then `uv run uvicorn app.main:app --app-dir backend --host 127.0.0.1`. Direct development defaults to an ignored SQLite local.db. Compose and CI use PostgreSQL.

For Docker, create `.env` only if it is missing, then run `docker compose up --build -d --wait`. This starts PostgreSQL, migrations, and the API on localhost:8000. Check `/api/health/ready`. Database data persists in a named volume. This is a local/test configuration.

Checks: `uv run ruff check backend`, `uv run ruff format --check backend`, `uv run mypy backend/app`, `uv run pytest`, and `uv run alembic check`. CI also tests PostgreSQL, migration upgrades/downgrades, dependency vulnerabilities, and Compose startup. TEST_DATABASE_URL must point only to a disposable database: tests reset its schema.

Tests mock Discord requests and do not send live messages. Ambiguous publication errors produce `needs_review`; a crash can leave `publishing`. Neither state is automatically retried, preventing accidental duplicate posts. Check Discord before recovering an event in either state. Publication and assignment announcements use REST; player signup interactions use the Gateway listener running inside the API.

Manual assignment: POST `/api/events/{id}/close` requires moderator access, the selected server/channel, and CSRF. The open → closing → review/assigned transition uses a two-minute claim lease. Closing freezes a secure seed and scoped profile weights, guarantees, and paired-player preferences once. Custom events use saved table selections; legacy polls end an unexpired Discord poll, wait for finalized result counts, and reconcile every paginated voter list before drawing. Incomplete/failing reads retain closing state without a lottery; retrying finishes with the same seed/weights. An interrupted claim can be recovered after its lease expires. Already-assigned requests return the saved event and never redraw.

Players can add a ❌ reaction to an assignment announcement to leave their assigned table before the event starts. The highest-priority remaining waitlisted player who selected that table is promoted. Withdrawals and promotions are stored separately from the immutable lottery result; signup rows and current assignment views reflect the updated roster. Promotion notices mention the new player in the event channel and are tracked with announcement messages so archive cleanup removes them.

The API lifespan worker checks expired open signups every five seconds and runs the same close-and-assign flow automatically. Discord finalization or reaction synchronization delays leave the event safely retryable; custom signup controls are disabled after assignment. Automatic closing shares `ANNOUNCEMENT_WORKER_ENABLED` with assignment delivery and is disabled when that setting is false.

The `preference-weighted-matching-v6` engine sorts players by `-ln(U)/weight` using reproducible independent hash draws from the recorded seed. Capacity-aware augmenting paths may move earlier accepted players between their selected tables but cannot evict them. A best-effort preference pass then arranges only those winners, without changing the winner set or extending individual guarantees; see [Paired Player Preferences](player-pairing.md). The event has one immutable lottery run containing the algorithm version, seed, input snapshot, complete placements, and original-order shared waitlist. GET `/api/events/{id}/assignments` exposes replay data to authorized moderators. The existing signups endpoint returns saved table placements/waitlists once assigned. Results are displayed in TableSignup and announced in the original Discord signup channel. Recurring publication, scheduled Discord events, and private waitlist-promotion notices use the same lifecycle worker. No live Discord polls are changed in automated tests.

Assignment announcements are inserted into a persistent queue in the lottery transaction and attempted immediately after commit. The API lifespan runs a delivery worker every five seconds (disable with ANNOUNCEMENT_WORKER_ENABLED=false in isolated tests). Multipart messages respect Discord content/mention limits; only seated players may be pinged, and private names/weights are never included. Confirmed failures retry with backoff and respect rate-limit retry delays. Stable nonces prevent recent duplicate sends; ambiguous sends and interrupted leases reconcile against bot-owned channel history, then require moderator review if still uncertain. The event modal shows delivery status and offers an explicitly confirmed retry without redrawing. Old already-assigned events can explicitly announce their saved results.

POST `/api/events/{id}/test-users` persists 0–1000 synthetic signups for the normal publish, close, assignment, and announcement flow. Set `TEST_SIGNUP_USER_IDS` to comma-separated Discord user IDs; `OWNER_DISCORD_ID` is always allowed. Authorization, destination scoping, and CSRF are enforced server-side. Zero clears test signups while preserving real votes and player profiles. Test announcements are marked TEST and do not ping users.

Test users are organization/personal-scoped saved profiles with `is_test=true`. Population reuses existing test identities and creates only missing profiles, defaulting to weight 5.0. Clearing signups or deleting an event preserves profiles. Profile PUT accepts weighting from 0.1–10 for test users; regular-player weights are editable through the same scoped profile API. Closing freezes current profile weights for the saved lottery.

Guaranteed seats are persistent, organization/personal-scoped profile settings for real and test players. Players must sign up; guarantees apply to any of their selected tables. The engine matches guaranteed players first, keeping each accepted player seated while filling remaining seats by weight. Closing freezes guarantees with weights for replay. A preflight checks current voters before ending the poll; finalized votes are validated again to handle votes changing during closure. Conflicts return 409 without a lottery or announcement and allow corrected settings on retry. A finalized poll cannot be reopened; its conflict must be resolved before placements are saved. Existing lottery results stay immutable.

POST `/api/events/{id}/archive` requires scoped moderator authorization and CSRF. It idempotently timestamps assigned events with saved placements, preserving the assigned status, lottery, signup data, and profiles. Cleanup removes promotion notices and the event thread; optional checkboxes also delete signup/assignment messages and the scheduled Discord event. The event listing includes archived records with `archived_at`.

Organization/personal-scoped General settings are read/written at `/api/settings/assignment` using the authenticated destination and CSRF on mutation. Automatic weight adjustment defaults on and is captured when closing starts. Successful placement applies +0.1 to each waitlisted player and −0.1 to each assigned player (including guaranteed and test players), clamped to 0.1–10, in the same transaction as the unique lottery run. New player profiles start at 5.0 before adjustment; names and other profile settings are preserved. Retries, announcement delivery, and archiving do not reapply adjustments. Migration `20261101_weight_adjustments` resets existing profile weights to 1.0 once, without changing saved lottery inputs/results.

DELETE `/api/settings` disconnects only the signed-in account with CSRF enforcement. An explicit disconnected state prevents the legacy server default from reconnecting it, including after sign-in. Events, profiles, server settings, and Discord messages are preserved. PUT `/api/settings` validates and restores a saved connection.

GET `/api/auth/connect` starts account-bound, single-use OAuth with identify/guilds/bot scopes and the existing registered callback URI. The callback verifies the signed-in account, resolves the authorized guild (validating any guild hint against bot access and live Manage Server permission), saves the server immediately, and returns to Settings. A new server can be saved with no channel; event APIs require a saved channel, while assignment settings require only the verified server. Selecting a channel uses the existing validated Settings PUT. Cancelled, mismatched, expired, and unauthorized callbacks never overwrite the saved destination.


Discord signup messages use a rich embed ordered as title, description, then dates/location and tables. Signup and assignment table fields share the same formatter, inline layout, and spacing; waitlists use a full-width field. Discord controls the final card width. Signup authorization requests Embed Links along with existing signup permissions. Closing a reaction signup adds an embed footer and retains its title, description, and tables; legacy text messages remain supported.

## Code organization

`app/main.py` composes the application. API paths and request schemas remain stable as features move into smaller modules:

- `app/routes/` groups HTTP endpoints by authentication, organizations, preferences, players, events, signups, assignments, and cleanup.
- `app/events/` owns publication, signup selections, recurring schedules, closing warnings, table membership, and exports.
- `app/assignments/` owns lottery algorithms, closing/finalization, withdrawals, promotions, and waitlist changes.
- `app/discord/` owns the Discord API client, Gateway listener, message formatting/delivery/cleanup, reaction synchronization, rosters, threads, and promotion DMs.
- `app/players/` owns organization-scoped player profile and pairing operations.
- `app/settings/` owns scoped General preferences, organization selection, and Discord connection settings.
- `app/context.py` supplies shared request authorization, destination scoping, database access, and serialization. Read endpoints use `scoped_event`; mutations retain their atomic SQL guards.
- `app/lifecycle.py` owns startup and the synchronization worker. `app/main.py` composes the application.
- `app/models.py`, `app/schemas.py`, `app/config.py`, `app/branding.py`, and `app/security.py` contain shared database definitions, request bodies, configuration, branding, and token hashing.

Package initializers are intentionally small. Import a service from its owning module, for example `from app.assignments.lottery import assign`, rather than re-exporting services through `app/__init__.py`.

See [the duplication review](code-sharing-review.md) for candidates for further shared functions and components.

API integration tests live in `backend/tests/test_api_*.py`, with the shared client fixture in `conftest.py` and workflow setup in `flow_helpers.py`. Run individual feature files or the full suite with `uv run pytest`.

Keep source and test files below 1,000 total lines. Run `python3 scripts/check_file_lengths.py` from the repository root; Repository basics CI enforces the same rule.

## Private waitlist promotion notices

General → Send private messages for waitlist promotions defaults on for new scopes and is scoped to the selected organization or personal events. When enabled, automatic promotions after a withdrawal and organizer moves from the waitlist queue a private bot message. Initial lottery placements, simulated players, and adding a known player who was not waiting do not trigger a DM. The option is independent of public table-change announcements.

Each message names the event, table, and start time and includes a **Give up my seat** button. The Gateway verifies the application, private message, and intended recipient, then uses the same locked withdrawal service as channel reactions. Repeated clicks cannot release another player's seat or promote anyone twice. Withdrawals stop when the event starts or is archived. The saved lottery draw remains unchanged.

`promotion_dms` is a separate durable delivery queue. The assignment commits before Discord is contacted; blocked inboxes never revoke a seat. Temporary errors and rate limits retry, while ambiguous sends are reconciled with message history before any further action. Unconfirmed delivery is recorded for review rather than blindly reposted. Archived events, expired events, disabled preferences, and players who no longer hold the promoted seat cancel pending notices. Public assignment updates continue independently. The existing Gateway listener must be running for DM buttons to work; no extra privileged intent is required.

New event threads start from a separate, short “Event updates” message rather
than the signup post, so signup controls and rosters do not become the thread's
starter. This message uses the existing announcement outbox for safe retries
and cleanup. Existing threads are preserved with their discussion history and
retain their original starter. No schema migration is needed.

Closing reaction signups now waits for already received Gateway actions for
that signup message to finish saving before taking the draw snapshot. New
actions arriving during closing wait for its outcome: closed events reject
them, while a failed close lets them apply. A write failure, disconnect gap, or
60-second backlog timeout prevents drawing. This coordination runs within the
single API/Gateway process documented above.

Assignment posts and their instructions/roster edits take precedence over
optional thread setup and notices, so a thread-starter retry cannot hold up the
results. Thread creation requests delivery of its own starter explicitly.
Discord REST calls share an application-owned HTTP pool, and request permission
checks release their database connection before contacting Discord.

Discord message code is grouped by responsibility: `discord/event_messages.py` builds signup and assignment payloads and queues roster messages; `discord/event_threads.py` owns neutral thread starters, thread creation, membership, and cleanup. `discord/delivery.py` shares atomic delivery leases, token-protected completion, uncertain-send reconciliation, and retry delays. Announcement dispatch and promotion DMs retain their own eligibility, privacy, and terminal-failure policies. Thread starters use these shared mechanics directly, avoiding a dependency on assignment dispatch.

## Assignment service map

- `assignments/roster.py`: `build_current_roster` and `build_roster_players` combine the immutable lottery result with withdrawals, manual seats, waitlist additions, and table exclusions. These functions read saved data without changing it.
- `assignments/player_changes.py`: event edit locking, organizer seating/removal/waitlist additions, pair-aware replacement selection, and withdrawals from channel announcements or private promotion messages. Callers retain the existing transaction and authorization boundaries.
- `assignments/notifications.py`: public table-change queueing, promotion text, and private promotion notice queueing.

The read-only roster module depends only on saved models and table-membership
filters. Notifications can read that projection and queue delivery work; player
changes call both services. Discord delivery no longer imports player-change
logic. Existing HTTP paths, `current_result` response fields, database tables,
and saved draw formats are unchanged. No migration is required.

Event API presentation lives in `events/event_views.py`. Event-list requests load scheduled Discord events, assignment delivery rows, and pairing-warning inputs in batches for the already scoped event list. `assignments/roster.py` accepts a typed `RosterRecords` bundle for these batch reads and computes waitlist membership once; single-event callers use the same projection. Name decoration reads only profiles and event settings for players present in the roster and retains the organization/personal scope filters.

`settings/general_settings.py` declares General Settings fields and enabled defaults. ORM defaults, unsaved preferences, and response mappings use that contract. Existing `/api/settings/assignment` paths and the `assignment_preferences` table remain compatible; older clients still preserve omitted saved options. No migration is needed.


## Cleanup and compatibility evidence

The #194 audit removed `.event-card` and `.draft-actions` CSS rules after checking that no application markup, scripts, or tests use either class. No generated class names are assembled for these selectors. The intentionally hidden Download all event signups control and its export logic remain intact.

`GuildSettings` is compatibility-only: application preference reads use `assignment_preferences.for_scope` / `for_event`, which always return saved values or enabled defaults. The `guild_settings` table is retained because `20261101_weight_adjustments` creates it and `20261104_assignment_backfill` reads its original choices when upgrading older installations. Keeping the table/model also preserves legacy values across historical downgrades; the disconnect compatibility test verifies that disconnecting does not erase them. Removing this table would require a new migration and an explicit decision about preserving its old values. Historical migrations are unchanged in this cleanup.

Shared signup fixtures/publication helpers live in `backend/tests/signup_helpers.py`; thread fixtures live in `thread_helpers.py`. Test modules import these helpers rather than other collected `test_*.py` files. The API fixture remains in `conftest.py`, with other workflow helpers in `flow_helpers.py` and `promotion_helpers.py`.

Browser refresh uses request-completion polling, not SSE: rosters refresh after two seconds while visible, announcement delivery after one second while pending or 15 seconds otherwise, and review-delivery checks after one second. See `frontend/src/lib/visiblePolling.ts` and its callers for the browser timers. The backend lifecycle loop still runs every five seconds; open Discord roster reconciliation has its own 30-second eligibility interval.

## Diagnosing private seat-withdrawal failures

Search API logs for `Promotion DM`. The Gateway logs each accepted click with its interaction, notice, user, channel, and message IDs. Rejected DM lookups log one or more explicit reasons: `notice_not_found`, `recipient_mismatch`, `notice_not_sent`, `channel_mismatch`, or `message_mismatch`. When a record exists, the same warning includes the event ID, saved recipient/channel/message IDs, delivery state, attempt count, and uncertain-delivery flag. A missing notice can indicate an old/deleted record or an instance using a different database; check the single-listener deployment rule before assuming either cause.

Other outcomes identify an unavailable event/draw, a player without a current seat, or a completed withdrawal. Gateway acknowledgement and response failures include Discord HTTP status/code and the same correlation IDs; processing exceptions retain their traceback. A response failure can happen after the withdrawal committed, so check the completion log before retrying. These logs use `uvicorn.error` at INFO for receipt/completion and WARNING for rejected checks or Discord response failures. They exclude DM content, player names, and credentials; the private user-facing messages remain unchanged.
