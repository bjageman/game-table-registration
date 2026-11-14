# Code sharing review

This review covers application code in `backend/app` and `frontend/src`. These are refactoring opportunities, not claims of confirmed user-facing defects. The backend folder reorganization changes module locations and imports; the extractions below are follow-up work.

## Recommended extractions

### 1. Weight input parsing and limit feedback

- [PlayerProfile.tsx](../frontend/src/features/players/PlayerProfile.tsx) — `saveWeight`.
- [EventTables.tsx](../frontend/src/features/events/assignments/EventTables.tsx) — `onSaveWeight`.

Both parse a string, reject empty/nonfinite values, clamp to 0.1–10, and construct identical minimum/maximum messages. Extract a pure `parseWeightInput` helper returning the normalized value and optional limit explanation, with shared bounds. Leave saving and feedback placement in each component. This is the smallest useful first refactor; it prevents future changes from treating profile and event weights differently.

### 2. Active organization and membership lookup

- [context.py](../backend/app/context.py) — `authenticated`.
- [connection_settings.py](../backend/app/settings/connection_settings.py) — settings, channels, save, and disconnect handlers.
- [auth.py](../backend/app/routes/auth.py) — `/api/me`.

Each loads `OrganizationSelection`, then the organization and membership. Extract a database helper returning a valid selected organization/member pair, including a single policy for missing memberships. Keep route-specific admin checks, destination requirements, and CSRF handling explicit. This deserves careful tests for removed memberships and personal-mode fallback because it affects authorization.

### 3. Assignment mutation locking

- [withdrawals.py](../backend/app/assignments/withdrawals.py) — `manager_add` and `manager_remove`.
- [waitlists.py](../backend/app/assignments/waitlists.py) — `add_player`.

All claim the same unarchived event in `assigned` or `review` with an atomic no-op UPDATE before reading and changing its result. Extract a helper for that specific claim and loading the event/draw. Keep the caller's transaction open through persistence and notification queueing. Do not replace the atomic claim with a plain SELECT or automatically broaden the permitted statuses.

### 4. Promotion notification construction and queueing

- [withdrawals.py](../backend/app/assignments/withdrawals.py) — `withdraw_seat`, `manager_remove`, and `manager_add`.

These repeat announcement part allocation, recipient filtering, durable announcement creation, and enqueueing promotion DMs/roster refreshes. Extract narrowly scoped helpers for enqueueing a public table-change message and notifying promoted players. The public text, nonce labels, and decision to notify should remain explicit inputs: organizer edits during verification intentionally behave differently from changes to published assignments.

### 5. Deterministic lottery sampling

- [lottery.py](../backend/app/assignments/lottery.py) — `digest` and `priority`.
- [paired_lottery.py](../backend/app/assignments/paired_lottery.py) — `digest` and `priority`.

Both derive the same SHA-256 digest, 52-bit uniform value, and exponential weighted priority. Extract seed/label sampling and weighted score functions. Preserve existing labels, numeric operations, and tie-breakers exactly so historical draws remain replayable. Keep pair grouping, average weights, guarantees, and allocation algorithms separate.

### 6. Player search data and matching

- [PlayerLookup.tsx](../frontend/src/features/players/PlayerLookup.tsx) — local `Player` type and search filter.
- [PlayerPairEditor.tsx](../frontend/src/features/players/PlayerPairEditor.tsx) — local `Candidate` type and `filterOptions`.
- [EventTables.tsx](../frontend/src/features/events/assignments/EventTables.tsx) — available-player type and suggestions.

All use the same Discord ID/name/display-name fields and normalize a query against those fields. Define a shared player summary type and matching function. Keep eligibility filtering, result limits, sorting, and presentation local; pairing and waitlist selection have different rules.

### 7. Backend event/template field validation

- [schemas.py](../backend/app/schemas.py) — `EventInput.validate_event` and `EventTemplateInput.validate_template`.

Blank-title and case-insensitive duplicate-table checks are repeated. Extract shared validators or a base model for the common fields. Retain each input's duration rules and the event-only date/deadline checks. The frontend already shares its event/template validation through `validateTemplate`, so another frontend abstraction is unnecessary here.

## Lower priority

Several frontend action components repeat busy/error state, access-error handling, confirmation state, and request cleanup. A small mutation hook may help after the domain extractions above. A universal action component would hide important differences: publication can be uncertain, archiving can partly succeed, and Discord cleanup can require multiple requests.

## Existing shared code to preserve

- `EventForm` already serves creation, recurring edits, and single-event edits.
- `event_scheduling.event_values` shares backend create/edit field conversion.
- `withdrawals.current_result` is the canonical projection of saved assignments plus organizer edits and withdrawals.
- `signup_messages.signup_body` and `discord_format` share Discord presentation and size limits.
- `ConfirmationDialog`, `FormField`, `useDialog`, `mutationOptions`, and `finishDiscordCleanup` already cover common UI/request behavior.

Suggested order: weight handling, player search, schema validation, organization resolution, assignment locking, promotion queueing, then lottery sampling with replay fixtures. Keep each extraction in a focused PR.
