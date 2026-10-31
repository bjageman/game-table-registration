# Frontend

Run `npm ci` and `npm run dev` from `frontend/`, then open http://localhost:5180. The moderator UI restores Discord sessions, starts OAuth login, and supports logout. Authentication uses server-owned cookies; the CSRF token stays in memory. The root `index.html` is a static preview; use `frontend/` for ongoing development.

For headless access, set `DEV_HOST=0.0.0.0` and `PUBLIC_URL=http://your-host:5180` in the root `.env`. The configured hostname is allowlisted. API proxying targets loopback port 8000. Register your PUBLIC_URL plus `/api/auth/callback` as the redirect URI in Discord's OAuth2 settings. Use the exact same origin in your browser.

Checks: `npm run lint`, `npm run build`, `npm test`, and `npx playwright install chromium && npm run test:e2e`. Stop any existing server on port 5180 before the browser tests. CI also builds the frontend Docker image. Browser tests mock the API and check login/logout on desktop and mobile without contacting Discord.

Run `docker compose -f compose.yml -f compose.frontend.yml up --build -d --wait` from the repository root. Open http://localhost:8080. Set PUBLIC_URL to your browser origin. The frontend Compose file extends the backend Compose file and is not a standalone deployment.

The event list loads the server's event records with start times, signup duration, table capacities, and publication status. Times use the browser's local timezone. Refresh retrieves the latest server state. A lost session or removed moderator access hides the dashboard. Events awaiting publication review show a check-Discord notice.

Create event opens a draft form for the title, local event date/time, whole-hour signup duration (1–768), and 1–10 tables with capacities (1–999, default 15). MUI X uses a combined date/time picker on desktop and separate date and time pickers on mobile, defaulting to the current time rounded up to the next 15-minute interval. The browser sends a timezone-qualified timestamp. Table names must be distinct, and the event must start after the signup window ends. Saving creates a draft; it does not publish a Discord message. Failed requests keep entered values for correction.

Drafts offer Publish to Discord with a confirmation dialog naming the event, tables, capacities, and signup duration. Confirmation sends one CSRF-protected publication request; the open event links to its Discord poll. A network error, server failure, or conflicting publication hides further publish controls until the list is refreshed from the server. Check Discord before retrying uncertain publication. Events already publishing or held for review never offer automatic retries.

Validation errors are associated with their fields, including errors returned by FastAPI. Local times that are missing or occur twice during daylight-saving transitions are rejected rather than silently shifted. Requests time out after 15 seconds; mutations are never automatically retried. Tests cover the complete mocked login/create/publish/logout journey, role/session loss, server validation, stalled/uncertain publication, and daylight-saving transitions on desktop and mobile.

For a manual acceptance check in a dedicated Discord test server: configure the OAuth callback for the exact PUBLIC_URL, log in as an allowed moderator, save a future draft, verify that no poll exists yet, then explicitly confirm publication and follow the Discord poll link. Refresh and confirm that the open event offers no publish action, then log out. This check sends a real poll only when you confirm publication.
