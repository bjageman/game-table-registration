# Game table registration

Run the API and frontend in one terminal from the repository root:

```bash
./run.sh
```

Requires Node.js/npm and either `uv` or an existing `.venv` with the backend
dependencies installed. Configure the root `.env` using `.env.example` first.
The script syncs Python dependencies when `uv` is available, installs frontend
dependencies if missing, applies database migrations, and starts both servers.
Press Ctrl+C to stop both. If either server exits, the other is stopped too.

The frontend defaults to http://localhost:5180. For access from another device,
set `DEV_HOST=0.0.0.0` and `PUBLIC_URL=http://your-host:5180` in `.env`, and
register `PUBLIC_URL` plus `/api/auth/callback` in Discord's OAuth2 settings.

See [backend setup](docs/backend.md) and [frontend setup](docs/frontend.md) for
configuration details and alternative startup methods.
