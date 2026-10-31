# Repository workflow

- Work on feature branches and commit completed changes.
- Open pull requests targeting `dev` for the owner to review manually.
- Never merge pull requests or branches, enable auto-merge, or use a merge queue.
- Never push directly to `dev` or `main` or bypass branch protections.
- The agent is NEVER authorized to merge into `main`.
- The human owner handles all merges and production promotions.
- Never commit `.env`, tokens, credentials, or local database files.
