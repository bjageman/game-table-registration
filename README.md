# TableSignup

Run the API and frontend in one terminal from the repository root:

```bash
./run.sh
```

Requires Node.js/npm and either `uv` or an existing `.venv` with the backend
dependencies installed. Configure the root `.env` using `.env.example` first.
The script syncs Python dependencies when `uv` is available, installs frontend
dependencies if missing, applies database migrations, and starts both servers.
Local API reloads also apply pending SQLite migrations before serving requests,
including after switching branches while the script stays running.
Press Ctrl+C to stop both. If either server exits, the other is stopped too.

When switching branches, an existing SQLite database may reference migrations
absent from that branch. In that case, `run.sh` reports the migration error and
leaves the database untouched. To keep branch data separate, choose another
SQLite file:

```bash
DATABASE_URL=sqlite:///./launcher-local.db ./run.sh
```

The frontend defaults to http://localhost:5180. For access from another device,
set `DEV_HOST=0.0.0.0` and `PUBLIC_URL=http://your-host:5180` in `.env`, and
register `PUBLIC_URL` plus `/api/auth/callback` in Discord's OAuth2 settings.

To rename the site, change its footer, or show a header logo, copy
`branding.example.json` to `branding/branding.json` and edit it. This file stays
on the server and is ignored by Git. Restart the API after changing it; without
the file, the site uses the TableSignup defaults. See
[deployment](docs/deployment.md) for separate hosted dev and production files.

See [backend setup](docs/backend.md) and [frontend setup](docs/frontend.md) for
configuration details and alternative startup methods.

See [deployment and promotion](docs/deployment.md) for hosted dev/prod setup,
GitHub secrets, and the feature → dev → main review process.
