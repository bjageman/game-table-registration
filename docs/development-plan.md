# TableSignup: development plan

Status: proposed architecture; no application or deployment has been implemented. Scope is one Discord community initially, with all records scoped to a guild so another community can be supported later.

## Product behavior

Moderators configure a weekly schedule in their local timezone: signup opening, signup closing, and the actual event date/time. Each event has up to 10 tables, usually 15 seats each, with individually editable capacity. Players select any tables they would attend in a single native Discord multi-answer poll. Choices are equally acceptable, not ranked; signup order gives no advantage. Each player receives at most one table per event.

At closing, freeze signups, reconcile the final Discord voter lists, run the weighted lottery, publish results, and notify players. Unassigned players enter a shared event waitlist with eligibility for their selected tables. When someone withdraws, immediately assign the highest-priority eligible waiting player, remove them from all other table eligibility, and notify them. Assignment commits immediately; Discord delivery may be delayed by outages or rate limits. Stop promotions at the event start time. Players can withdraw using a persistent button or slash command, including leaving the waitlist.

## Stack and service layout

Use Python with FastAPI for the moderator API, discord.py for the bot, SQLAlchemy and Alembic for PostgreSQL access and migrations, and Pydantic for validation. PostgreSQL is the source of truth for schedules, assignments, durable jobs, and notification delivery. Start without Redis/Celery: a database-backed worker is sufficient for this workload and easier to operate.

Match the neighboring tiny-grimoire app's UI tools: React, TypeScript, Vite, Tailwind CSS, Lucide icons, clsx, and tailwind-merge. Use Vitest/Testing Library and Playwright as it does. Select and lock compatible supported versions during scaffolding rather than copying version ranges blindly. Python checks use Ruff, mypy, pytest, and Hypothesis.

One repository: `backend/` contains shared domain logic, API, bot, worker, and migrations; `frontend/` contains the moderator UI; `tests/`, `docs/`, and `.github/workflows/` hold verification and operations. API and bot use the same domain service functions so business rules cannot diverge.

Docker Compose runs web (static frontend and /api reverse proxy), API, bot/worker, and PostgreSQL as separate services. API and bot can share one built Python image with different commands. Only web joins the existing external nginx-proxy network from the supplied example; API and database use a private internal network. Preserve VIRTUAL_HOST/LETSENCRYPT_HOST integration with the host's TLS proxy. Use separate Compose projects, domains, databases, volumes, Discord applications/tokens, and test channels for dev and production. No dependency on this development machine's paths or Docker socket.

## Discord poll integration

User confirmed a maximum of 10 tables (currently five, expected maximum eight). Use one native poll message listing names and capacities, plus closing and event timestamps. Reject oversized table descriptions/message content in the editor before publishing. Enable multiple answers; voting means entering a lottery, not reserving a guaranteed seat.

Discord polls accept an integer duration in hours, have a maximum duration of 32 days, and can be ended early. Configure the native expiry rounded up to cover the requested deadline; the durable scheduler ends the poll at that deadline. Enable the guild message poll intent and required channel permissions. Do not request Message Content access for this workflow.

Consume vote add/remove events for a live preview, but reconcile all paginated answer-voter lists after the poll has ended and results are finalized. Counts alone are insufficient. Deduplicate users across answers and exclude bot accounts. Retry finalization and voter retrieval before assigning anyone. Save the message ID, answer-to-table mapping, final snapshot, and reconciliation status. After a restart, recover overdue jobs and reconcile existing messages rather than blindly reposting them.

Important native-poll limitation: if the bot is offline at a custom deadline before Discord's own expiry, later votes can arrive and final voter lists do not provide a reliable historical cutoff snapshot. Mark that event for moderator review and do not silently run a supposedly exact-cutoff lottery. The UI should recommend whole-hour windows, where native expiry acts as an independent fallback. If exact arbitrary deadlines during outages become mandatory, replace native polling with bot-controlled selections in a later iteration.

Once published, freeze table options and capacity for the MVP. Moderators may edit event metadata and future schedules, cancel an event, or explicitly cancel/repost an open signup with a warning that votes must be re-entered. Never silently discard votes or rerun published assignments.

## Scheduling and editing

Store the IANA timezone and weekly local wall-clock rule, plus explicit UTC timestamps on each generated event. Materialize a rolling eight-week horizon, with a uniqueness key per schedule occurrence. Validate opening < closing < event start. Preview daylight-saving transitions and require explicit resolution of ambiguous/nonexistent local times rather than guessing.

The dashboard lists upcoming events with opening, closing, event time, timezone, and status. Editing offers this occurrence or future unpublished occurrences. Existing open/assigned occurrences retain their snapshots. Allow skipped weeks and cancellations. Show a preview of affected dates before saving recurring changes.

Use states draft, scheduled, open, closing, assigned, completed, cancelled, and needs-review. Workers claim durable jobs with leases/row locks, and all transitions check current state and a unique operation key. Two workers or retries must not create two lotteries. Recover overdue opening/closing jobs only while the event is still actionable; expired events are flagged rather than posting stale signups.

## Lottery and fairness

Per-user guild weights default to 1.0; allow positive values such as 0.5 for reduced priority and 2.0 for increased priority, with a documented bounded range (proposed 0.1–10). Keep eligibility bans separate from weighting. Record moderator, reason, and changes in an audit log. Snapshot weights when signups close; later changes affect future lotteries only. Never display private weight values publicly.

Generate a weighted random permutation without replacement: draw an independent U in (0,1) for each player and sort by -ln(U)/weight ascending. Use a securely generated seed, record algorithm version, input snapshot, seed, and output for moderator replay. A weight of 2 doubles relative priority against weight 1 in a pairwise draw; it does not guarantee twice the final admission probability, which also depends on selected tables and capacity.

Process players in lottery order using a capacitated bipartite matching algorithm with augmenting paths. A newly considered player may cause an earlier accepted player to move to another selected table, but must not evict an earlier accepted player. Randomize table tie-breaking reproducibly. This preserves lottery priority while avoiding avoidable empty seats caused by greedily giving a flexible player the only seat a later player could use. Freeze all placements before publication. Verify the algorithm against a brute-force oracle on small cases.

Use the same original lottery order for the waitlist; never redraw after a dropout. Promotion considers only unassigned, active players who selected that table. Existing published assignments do not move during promotion. Serialize concurrent withdrawals/promotions using event locking and database constraints; maintain an event/player unique active assignment and enforce table capacity transactionally. Promotion notifications are inserted into an outbox in the same transaction as the assignment.

## Data and authorization

Core entities: guild settings (channel/moderator roles/timezone), Discord users, recurring schedules, event occurrences, table templates, event table snapshots, player weight history, signups/selected tables, lottery runs and entries, assignments, withdrawals, audit entries, durable jobs, sessions, and notification outbox. Use Discord IDs as strings at API/JavaScript boundaries to avoid numeric precision loss. Retain snapshots sufficient for replay; define a retention policy before production.

Discord OAuth2 login uses authorization code flow, validated state and redirect URI, and server-side sessions in Secure/HttpOnly/SameSite cookies. Request only identity and membership scopes actually needed; no email scope. Verify guild membership and configured moderator roles server-side for every privileged operation, with short-lived role caching and fail-closed behavior. Bootstrap the owner by configured Discord ID. Protect mutations against CSRF, rotate sessions, rate-limit login/mutations, and keep Discord tokens server-side. Never trust a guild ID or role sent by the browser.

Provide a Discord user search/ID lookup for weights, displaying the resolved user and checking guild membership. Allow positive/reduced weights with a reset-to-default action. Record schedule changes, weight changes, cancellations, and administrative overrides. Any manual assignment override must honor capacity and one-table rules and be audited.

## Moderator UI

Build a responsive, accessible dashboard with upcoming schedules as the landing page. Each event shows times, table capacities, signup counts, status, and a link to its Discord post. Event editing includes a weekly recurrence preview and clear timezone labels. Separate screens cover player weights, results/waitlist, and server settings. Show save validation inline, confirm destructive cancellations, and include empty/loading/error states and keyboard navigation.

Results show assigned players by table and the eligible waitlist per table derived from the shared queue. Display delivery failures and events needing review, with safe retry controls. A blocked DM does not cancel a reservation: publish a configurable channel mention fallback and keep the assignment visible via a player status command. Avoid mentioning arbitrary roles or everyone when rendering user-entered text.

## Reliability and operational behavior

Database transactions guarantee one committed lottery and consistent promotions. Discord side effects are delivered through a retrying outbox with backoff and dead-letter visibility. External sends cannot be promised exactly once: reconcile stored message identifiers and use operation identifiers where supported; surface ambiguous sends for repair instead of silently duplicating announcements. Log identifiers and errors without secrets or OAuth codes.

Use readiness/liveness checks, structured logs, alerts for overdue jobs and failed deliveries, persistent database volumes, scheduled off-host backups, and a documented restore drill. Run migrations once as a release step, not concurrently on each service startup. Use backward-compatible expand/contract migrations so rolling back an image does not require destructive schema downgrades.

## CI and local → dev → production

Tinygrim provides separate lint, typecheck, build, unit/integration tests, image build, dev deploy, production deploy, and dev-to-main enforcement workflows. Retain those categories and its review stages; improve deployment ordering so a push cannot deploy ahead of required checks. Use manual production review rather than its scheduled release auto-merge.

1. Local feature branch: locked installs, formatter/linter/type checks, pytest, Vitest, and a Compose smoke test. Use a dedicated Discord test server for real OAuth/poll checks; never production credentials in tests.
2. Pull request to dev: require backend Ruff/mypy, frontend ESLint/tsc, unit tests, PostgreSQL integration tests, frontend build, Playwright moderator journeys, migration checks, image build/Compose smoke test, secret scanning, dependency auditing, and container scanning. Pin action revisions, minimize token permissions, and never expose deployment credentials to untrusted PR jobs.
3. Human-reviewed merge to dev: build and publish commit-addressed images after checks pass, deploy those exact digests to the dev host/environment, run migrations and smoke tests, then exercise real Discord signup/close/withdraw flows in the test guild. Serialize deployments per environment and prevent stale runs from overwriting newer ones.
4. Reviewed release PR from dev to main: require successful checks and recorded dev acceptance. Promote the exact image digests tested in dev; attach a release manifest recording source SHA, schema version, and digests. If the release changes application contents, rebuild and retest in dev before promotion.
5. Production: explicit owner-controlled promotion after review (protected GitHub environment where supported, otherwise a maintainer-controlled release workflow). Back up, migrate, deploy, health-check, and keep the previous manifest for rollback. Restore database backups only as a planned recovery operation, not automatic rollback.

Require PR review and checks on dev/main, and enforce dev as main's release source. Use short-lived or narrowly scoped server deployment credentials. Keep server paths, domains, SSH details, and bot secrets in environment configuration, never source control. Reusable checks should run on PRs and release candidates, with a final required gate that cannot succeed if dependent jobs failed or unexpectedly skipped.

Meaningful coverage includes: lottery uniqueness/capacity/eligibility and statistical weight checks; matching oracle cases; ties and zero applicants; repeat finalization; overlapping scheduler workers; simultaneous dropouts; waitlist removal; frozen weights; DST and recurrence edits; authorization and CSRF failures; Discord pagination/reconnect/429/403/blocked DMs; interrupted database transactions; migration from a prior schema; and backup restoration. Use seeded statistical tests with generous justified bounds to avoid flaky probability assertions. End-to-end CI uses a fake Discord boundary; a documented dev-guild test validates actual platform behavior before releases.

## Delivery sequence and acceptance

1. Foundation and CI baseline (#1, #7): project structure, database migrations, locked dependencies, Compose, health checks, and checks on every PR.
2. Authentication and settings (#2): real Discord login in dev; unauthorized users cannot mutate any guild resource.
3. Scheduling and polling (#3, #4): configure a week, publish exactly one recoverable poll, collect multi-table choices, reconcile closure after restart.
4. Lottery and waitlists (#5): deterministic replay, matching properties, concurrent-dropout safety, and notification retries demonstrated.
5. Dashboard completion (#6): edit upcoming occurrences, manage weights, inspect results and failures on desktop/mobile.
6. Release hardening (#7): full checks, dev-guild acceptance, backups/restore, image promotion, and rollback rehearsal before the first production event.

Issues remain short; this document carries the detailed specification. Native poll choice and ten-table cap are confirmed. Proposed defaults for review are unranked choices, equal initial weights, frozen settings on publication, original-order waitlists, and promotion until event start. Exact server domain/channel/role configuration is needed during setup, not to complete this plan.

## References

- Local comparison: ../tiny-grimoire/package.json and ../tiny-grimoire/.github/workflows/.
- Hosting reference: docker-compose.example.yml in this repository.
- Discord polls: https://docs.discord.com/developers/resources/poll
- Discord OAuth2: https://docs.discord.com/developers/topics/oauth2
- Discord components: https://docs.discord.com/developers/components/reference
- FastAPI: https://fastapi.tiangolo.com/
- discord.py: https://discordpy.readthedocs.io/en/stable/
