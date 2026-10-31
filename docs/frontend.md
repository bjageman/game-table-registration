# Frontend

Run `npm ci` and `npm run dev` from `frontend/`, then open http://localhost:5180. The moderator UI restores Discord sessions, starts OAuth login, and supports logout. Authentication uses server-owned cookies; the CSRF token stays in memory. The root `index.html` is a static preview; use `frontend/` for ongoing development.

For headless access, set `DEV_HOST=0.0.0.0` and `PUBLIC_URL=http://your-host:5180` in the root `.env`. The configured hostname is allowlisted. API proxying targets loopback port 8000. Register your PUBLIC_URL plus `/api/auth/callback` as the redirect URI in Discord's OAuth2 settings. Use the exact same origin in your browser.

Checks: `npm run lint`, `npm run build`, `npm test`, and `npx playwright install chromium && npm run test:e2e`. Stop any existing server on port 5180 before the browser tests. CI also builds the frontend Docker image. Browser tests mock the API and check login/logout on desktop and mobile without contacting Discord.

Run `docker compose -f compose.yml -f compose.frontend.yml up --build -d --wait` from the repository root. Open http://localhost:8080. Set PUBLIC_URL to your browser origin. The frontend Compose file extends the backend Compose file and is not a standalone deployment.

The event list loads the server's event records with start times, signup duration, table capacities, and publication status. Times use the browser's local timezone. Refresh retrieves the latest server state. A lost session or removed moderator access hides the dashboard. Events awaiting publication review show a check-Discord notice.

Create event opens a draft form for the title, local event date and time, whole-hour signup duration (1–768), and 1–10 tables with capacities (1–999, default 15). The combined date/time picker offers 15-minute time choices and uses the browser timezone; the API receives a timezone-qualified timestamp. Table names must be distinct, and the event must start after the signup window ends. Saving creates a draft; it does not publish a Discord message. Failed requests keep entered values for correction.
