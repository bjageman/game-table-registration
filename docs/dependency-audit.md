# Temporary frontend audit exception

The owner approved a temporary exception on November 17, 2026 for
[GHSA-fc5q-39xc-vjpf](https://github.com/advisories/GHSA-fc5q-39xc-vjpf).
At review, picomatch 4.0.7 was the latest release and no patched release was
available. Installed copies are development dependencies of Vite, Vitest, and
related glob tooling. These tools use repository-maintained glob patterns;
the application does not accept user-supplied glob patterns for them.

The exception is recorded in `frontend/audit-exceptions.json` and expires at
**00:00 UTC on December 1, 2026**. CI fails after that date until the exception is
removed or explicitly reviewed again. There is no automatic extension.

`npm run audit:ci` enforces these rules:

- Audit production dependencies separately and block findings at every severity.
- Keep blocking other high and critical advisories throughout the full dependency tree.
- Match this exception by advisory URL, package name, and installed version 4.0.7.
- Require every installed copy and every dependency path using the exception to
  be marked development-only in the lockfile. Missing lockfile entries fail the check.
- Resolve inherited findings to their underlying advisories, so accepting this
  advisory does not accept an unrelated advisory on Vite, Vitest, or another parent.
- Fail on audit network errors, unsupported reports, or unresolved dependency paths.

Remove the exception as soon as a patched release is available and adopted.
Update the lockfile, remove the policy entry, and run `npm run audit:ci`,
`npm run test:audit`, the frontend build, and tests. If no patch is available before
expiry, a maintainer must explicitly review the risk before changing the date.

Run `npm audit` to see the raw findings without the exception policy.
