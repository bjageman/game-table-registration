# Frontend

Run `npm ci` and `npm run dev` from `frontend/`, then open http://localhost:5180. This React/TypeScript/Vite/Tailwind app displays only inactive Register and Login placeholders. The root `index.html` from the initial foundation PR is a static preview; use `frontend/` for ongoing development.

For headless access, set `DEV_HOST=0.0.0.0` and `PUBLIC_URL=http://your-host:5180` in the root `.env`. The configured hostname is allowlisted. API proxying targets loopback port 8000; the placeholder page does not call the backend.

Checks: `npm run lint`, `npm run build`, `npm test`, and `npx playwright install chromium && npm run test:e2e`. Stop any existing server on port 5180 before the browser tests. CI also builds the frontend Docker image. Browser tests check the placeholder at desktop and mobile sizes.

After both backend and frontend PRs are merged, run `docker compose -f compose.yml -f compose.frontend.yml up --build -d --wait` from the repository root. Open http://localhost:8080. Set PUBLIC_URL to your browser origin when connecting authentication in the future. The frontend Compose file extends the backend Compose file and is not a standalone deployment.
