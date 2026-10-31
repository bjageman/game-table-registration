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
Register these OAuth redirect URLs in the respective Discord applications:

- `https://signups-dev.brodin.rocks/api/auth/callback`
- `https://signups.brodin.rocks/api/auth/callback`

Add repository Actions secrets `DEPLOY_HOST`, `DEPLOY_USER`, and `DEPLOY_KEY`,
just as in Tinygrim. These secrets are repository scoped and must be configured
here even when their values match Tinygrim. The key must allow SSH to this server.

## Review and release

1. Branch from `dev`, make changes, and open a feature PR targeting `dev`.
2. Review CI and merge the PR manually. The push to `dev` deploys development.
3. Test the dev website and Discord flow.
4. Open a PR from `dev` into `main`. The source-branch workflow rejects other sources.
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
