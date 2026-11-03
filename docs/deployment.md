# Deployment and promotion

Production: https://signups.brodin.rocks (`main`).
Development: https://signups-dev.brodin.rocks (`dev`).

## Server setup

Clone this repository at `/tank/apps/docker/vibes/game-table-registration`.
The SSH deployment user needs GitHub read access, Docker socket access at
`/tank/services/docker.sock`, Bash, flock, Git and Docker Compose v2 with include support.
Use the existing `nginx-proxy` external network and its certificate companion.
Point both DNS names to this server and allow incoming HTTP/HTTPS.

Copy `.env.dev.example` to `.env.dev` and `.env.prod.example` to `.env.prod`.
Set EMAIL and a different random hexadecimal POSTGRES_PASSWORD for each environment.
Fill in Discord credentials separately; use a separate dev Discord application,
bot and test server/channel to avoid publishing test polls into production.
Restrict permissions with `chmod 600 .env.dev .env.prod`.
To customize the website name, footer, or header logo, copy
`branding.example.json` to `branding/dev/branding.json` or
`branding/prod/branding.json` in the persistent server checkout. These files
are ignored by Git and mounted read-only into the matching API container.
The logo URL must be HTTPS or a root-relative path that your web server serves.
If a branding file is absent, the site uses TableSignup defaults. The API reads
the file at startup, so redeploy after changing it. For local `./run.sh`, use
`branding/branding.json`; `compose.yml` mounts that same directory.
Register these OAuth redirect URLs in the respective Discord applications:

- `https://signups-dev.brodin.rocks/api/auth/callback`
- `https://signups.brodin.rocks/api/auth/callback`

For custom table signups, keep `DISCORD_GATEWAY_ENABLED=true` and
`DISCORD_SIGNUP_MODE=custom` in the environment file. The existing
`DISCORD_BOT_TOKEN` is all the listener needs to connect. In Discord Developer
Portal → the matching application → General Information, **clear the Interactions
Endpoint URL and save** if one was previously configured. `DISCORD_PUBLIC_KEY`
is no longer required and can be removed from environment files.

The API starts the Gateway connection automatically, reconnects after network
interruptions, and closes it on shutdown. Look for `Discord signup Gateway
connected` in the API logs before publishing. Connection/configuration failures
are logged, and publication remains blocked while the listener is disconnected.
Run one API replica with one Uvicorn worker per application. Keep dev and production
applications separate; stop a hosted dev instance before using its bot locally.
No tunnel, public interactions URL, port forwarding, or privileged intents are
needed. Local development continues using the existing LAN IP, PUBLIC_URL, and
OAuth redirect. Hosted deployments retain their normal website/OAuth HTTPS URLs.
`DISCORD_SIGNUP_MODE=poll` retains native publication during rollout, and existing
published native polls continue working in either mode.

For acceptance testing in the dedicated dev server, publish a future event with
two tables. The bot should add 1️⃣ and 2️⃣ under the signup message. As a regular
member, react to both; verify the organizer sees that player under both tables.
Remove 1️⃣ and verify the player remains under only the second table. Try another
member and close signups; the saved assignments must use those choices. New
installations require the bot's **Add Reactions** permission in the signup channel.
Existing menu-based events and native polls continue through their original paths.
If the bot is disconnected across a signup deadline, closing is held for review
because Discord cannot reveal when reactions were added during the outage.

Add repository Actions secrets `DEPLOY_HOST`, `DEPLOY_USER`, and `DEPLOY_KEY`,
just as in Tinygrim. Add `DEV_TO_MAIN_SECRET` with a token allowed to create
pull requests so release PRs trigger the normal CI checks. These secrets are repository scoped and must be configured
here even when their values match Tinygrim. The key must allow SSH to this server.

## Review and release

1. Branch from `dev`, make changes, and open a feature PR targeting `dev`.
2. Review CI and merge the PR manually. The push to `dev` deploys development.
3. Test the dev website and Discord flow.
4. Open a PR from `dev` into `main`, or use **Release dev → main** in Actions.
   Like Tinygrim, it also runs Wednesdays at 00:00 UTC and opens/reuses the release
   PR. Scheduled workflows start once the workflow reaches the default branch.
   Unlike Tinygrim, merges remain manual as required by this repository’s AGENTS.md.
   The source-branch workflow rejects other sources.
5. Review checks and merge manually. The push to `main` deploys production.

Configure GitHub branch protection on both branches to require PRs and passing
checks, including `check-source-branch` on main. The workflow alone does not
prevent direct pushes. Agents never merge or promote releases.
The existing frontend CI remains manually triggered as configured previously.

## Manual deployment

After the deployment changes have been merged into the appropriate branch:

```bash
./scripts/deploy.sh dev
./scripts/deploy.sh prod
```

Deployments build a clean snapshot of the remote branch, apply migrations,
and wait for API readiness before starting the web service. They do not change
the server checkout. Dev and prod have distinct Compose projects, images,
networks and PostgreSQL volumes; only the web services join nginx-proxy.
No host application/database ports are published. Redeployments retain data.
Back up PostgreSQL before promoting database changes; application rollback does
not undo migrations. A failed migration stops deployment before API replacement.

## Separate branded instances

The shared hosted Compose file defines the services. The dev/prod wrappers set
project names, while `scripts/deploy.sh` selects the brand's configuration:

```bash
./scripts/deploy.sh prod generic
./scripts/deploy.sh prod phillybotc
./scripts/deploy.sh dev phillybotc
```

Create `.env.generic.prod`, `.env.phillybotc.prod`, and `.env.phillybotc.dev`
from the corresponding `.env.prod.example` or `.env.dev.example` first.
Use separate Discord applications/bot tokens for simultaneously running instances,
unique hostnames, and separate PostgreSQL passwords. Set each Discord application's
OAuth callback to its instance's hostname plus `/api/auth/callback`.

Brand identifiers use lowercase letters, digits, and single hyphens. They are
stable deployment identifiers, independent of the display name in branding JSON.
For `phillybotc` production, the script uses:

- Compose project `game-table-registration-phillybotc-prod` (containers, private
  network, and database volume belong to this project).
- Images tagged `phillybotc-prod`, so building another brand cannot replace them.
- Private settings in `.env.phillybotc.prod`.
- Branding JSON in `branding/phillybotc/prod/branding.json`.
- Logo files in `branding/phillybotc/prod/public/`, served at `/branding/`.

Only the shared external `nginx-proxy` network connects the web containers.
Each brand runs its own PostgreSQL container and volume, even when the internal
database name is the same. `DATABASE_NAME` defaults to `tables` and may be set
before initialization. Changing it on an existing volume does not create or
migrate databases; provision the database before running migrations.

Existing commands without a brand retain their existing project names, image
tags, environment files, and database volumes. Existing GitHub workflows continue
to deploy these legacy instances; branded instances are deployed explicitly with
the commands above after owner promotion to the appropriate branch.

A new brand project starts with an empty database. Moving an existing installation
requires a deliberate PostgreSQL backup/restore into the new project's database
and a hostname cutover after stopping the old instance. Renaming a brand does not
move its data. Do not run old and new instances with the same bot token or hostname.

`docker-compose.example.yml` is a direct Compose alternative using the same hosted
services. Set `BRAND_ID`, `DEPLOY_ENV`, absolute `APP_ENV_FILE` and
`BRANDING_CONFIG_DIR`, plus the required password, hostname, and email in the
selected environment file. Create `BRANDING_CONFIG_DIR/public` before starting it.
Use the deployment script for remote-branch builds and ordered migrations.
