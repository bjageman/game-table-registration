# Repository workflow

- Work on feature branches and commit completed changes.
- Open pull requests targeting `dev` for the owner to review manually.
- Never merge pull requests or branches, enable auto-merge, or use a merge queue.
- Never push directly to `dev` or `main` or bypass branch protections.
- The agent is NEVER authorized to merge into `main`.
- The human owner handles all merges and production promotions.
- Never commit `.env`, tokens, credentials, or local database files.

# Code structure

- Keep every source and test file below 1,000 total lines, including comments and blank lines.
- Split modules by feature or responsibility before reaching that limit; share duplicated domain logic in focused functions.
- The limit covers Python, TypeScript/TSX, JavaScript/JSX, CSS, and shell files. Generated files, dependencies, lockfiles, and data are excluded.
- Run `python3 scripts/check_file_lengths.py` before committing. CI enforces the same limit.
