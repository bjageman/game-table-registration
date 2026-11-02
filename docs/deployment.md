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

For custom table signups, add each application's **General Information → Public Key**
as `DISCORD_PUBLIC_KEY` in its environment file and keep `DISCORD_SIGNUP_MODE=custom`.
After the signed endpoint is deployed, save these **Interactions Endpoint URLs** in
the respective applications' General Information pages:

- Dev: `https://signups-dev.brodin.rocks/api/discord/interactions`
- Production: `https://signups.brodin.rocks/api/discord/interactions`

Discord sends a signed PING when saving; the endpoint must be publicly reachable
over HTTPS. Use a separate application per environment because an application has
one interactions endpoint. No new OAuth redirect, Gateway worker, or privileged
intent is needed. Until setup is complete, custom publication is blocked before
sending any message. Set `DISCORD_SIGNUP_MODE=poll` to retain native publication
during rollout. Existing published native polls continue working in either mode.

For acceptance testing in the dedicated dev server, publish a future event with
two tables. As a regular server member, click **Choose tables / My signup**, select
both tables, and reopen the menu to confirm saved selections. Change to one table,
verify the organizer view, withdraw, and rejoin. Confirm another member's menu
shows only their own choices. Close signups as the organizer, verify assignments
use the selected tables and appear in Discord, then confirm an old private menu
cannot change the saved entries. Let a separate short signup window expire and
confirm its controls reject changes even before the organizer closes it.

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
