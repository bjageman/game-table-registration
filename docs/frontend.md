# Frontend

Run `npm ci` and `npm run dev` from `frontend/`, then open http://localhost:5180. The moderator UI restores Discord sessions, starts OAuth login, and supports logout. Authentication uses server-owned cookies; the CSRF token stays in memory. The root `index.html` is a static preview; use `frontend/` for ongoing development.

For headless access, set `DEV_HOST=0.0.0.0` and `PUBLIC_URL=http://your-host:5180` in the root `.env`. The configured hostname is allowlisted. API proxying targets loopback port 8000. Register your PUBLIC_URL plus `/api/auth/callback` as the redirect URI in Discord's OAuth2 settings. Use the exact same origin in your browser.

Checks: `npm run lint`, `npm run build`, `npm test`, and `npx playwright install chromium && npm run test:e2e`. Browser tests start their own server on port 5181, leaving the development server on 5180 available. Set `PLAYWRIGHT_PORT` to use another port. CI runs automatically on pull requests and pushes to dev/main, and also builds the frontend Docker image. Browser tests use shared API fixtures and check moderator journeys on desktop and mobile without contacting the backend or Discord. Feature routes override the common read-only defaults; unexpected API requests fail the test. CI retains traces and screenshots for browser failures.

Run `docker compose -f compose.yml -f compose.frontend.yml up --build -d --wait` from the repository root. Open http://localhost:8080. Set PUBLIC_URL to your browser origin. The frontend Compose file extends the backend Compose file and is not a standalone deployment.

The event list loads the server's event records with start times, signup duration, table capacities, and publication status. Times use the timezone selected in Preferences, falling back to the browser timezone. Refresh retrieves the latest server state. A lost session or removed moderator access hides the dashboard. Events awaiting publication review show a check-Discord notice.

Create event opens a draft form for the title, start, optional end, signup closing offset, and 1–10 tables with capacities (1–999, default 15). MUI X uses combined date/time pickers on desktop and separate date and time pickers on mobile, with 15-minute selection steps. The initial reference is the next whole hour. The end defaults to four elapsed hours after the start until manually edited. Unscheduled signups can close manually or a whole number of hours before the event; scheduled events specify opening/closing offsets and can repeat. The browser resolves wall times in the selected timezone and sends UTC timestamps. Saving a draft does not publish to Discord; failed requests retain the form.

Drafts offer Publish to Discord with a confirmation dialog naming the event, tables, capacities, and signup duration. Confirmation sends one CSRF-protected publication request; the open event links to its Discord signup message. A network error, server failure, or conflicting publication hides further publish controls until the list is refreshed from the server. Check Discord before retrying uncertain publication. Events already publishing or held for review never offer automatic retries.

Validation errors are associated with their fields, including errors returned by FastAPI. Local times that are missing or occur twice during daylight-saving transitions are rejected rather than silently shifted. Requests time out after 15 seconds; mutations are never automatically retried. Tests cover the complete mocked login/create/publish/logout journey, role/session loss, server validation, stalled/uncertain publication, and daylight-saving transitions on desktop and mobile.

For a manual acceptance check in a dedicated Discord test server: configure the OAuth callback for the exact PUBLIC_URL, log in as an allowed moderator, save a future draft, verify that no signup message exists yet, then explicitly confirm publication and follow the Discord signup link. Refresh and confirm that the open event offers no publish action, then log out. This check sends a real signup message only when you confirm publication.

Unpublished drafts offer Edit draft and Delete draft. Editing reuses the event form with the saved values; deleting requires confirmation. Both mutations require moderator access and CSRF protection and atomically require draft status, preventing changes after publication begins. Publication reloads the claimed event before constructing its signup payload so a prior committed edit is included.

The event modal retrieves saved Discord reaction selections (or current voters for legacy polls) per table. Rosters, including saved assignments, refresh two seconds after each completed request while visible. Public shared rosters use the same interval. Polling pauses in hidden tabs, resumes immediately on return, and never overlaps requests. Event lists retain manual refresh; no SSE connection is opened. Announcement status refreshes after one second while pending and 15 seconds otherwise; archived announcements stop polling. Review delivery checks use a one-second interval. Removing a table reaction updates the roster after the Gateway saves it. Counts show preferences relative to capacity; a player can select multiple tables. Lookup failures preserve the last loaded list and display an error.

Open signups can be deleted from the modal header. Confirmation offers optional Discord cleanup; failure retains the event for retry. Deleting an event removes its event data, not saved player profiles. Player names open Player Information with Discord identity, editable display name, weighting, guarantee, and a searchable paired-player input. Profiles are independent within each organization or personal workspace, additionally keyed by guild and Discord user ID. The same Discord account can have unrelated names, weights, guarantees, and pairs in different organizations. Profile saves require moderator authorization and CSRF protection.

The profile dropdown links to Player Lookup (`/#/players`) above Settings and Log Out. Player Lookup searches players with saved profiles or signup/assignment history for the selected server; its columns show Priority (starred when Guaranteed Seat is enabled), Discord username, display name, weighting, and test status. Click a column header to sort ascending; click it again to reverse the order. A chevron marks the active sort direction. Selecting a player opens Player Information for profile edits. The profile dropdown also links to Settings (`/#/settings`). Connect opens Discord authorization in the current tab. After authorization, the callback saves the chosen server and returns to Settings showing Disconnect and the saved server. Users then choose and save an eligible signup channel. The selection persists per account, and new accounts are guided through setup before seeing events. Changing servers/channels changes the displayed event list without moving or republishing old signup messages. Existing app moderators keep access to the legacy default destination.

Open signup modals offer Close Signups. With Review assignments before sending to Discord enabled, closing draws saved placements and opens an editable verification page without a confirmation modal or Discord assignment post. Send to Discord then opens confirmation with optional signup-message deletion. Delivery must succeed before entering assigned status; failures show an error and preserve the queued results. With review disabled, Close Signups opens confirmation and draws/posts directly. Closing freezes saved selections, weights, pairs, and guarantees. Legacy polls must finalize before drawing; interrupted closing can resume without a new seed.

Before an event starts, a player can add a ❌ reaction to an assignment announcement to leave their table. The highest-priority waitlisted player who selected that table is promoted and mentioned in a channel update. There is no confirmation step yet. Promotion updates are deleted from Discord when the event is archived; the saved lottery result remains unchanged.

Allowlisted accounts see Populate Test Users on draft and open event modals. Confirming adds persistent test players for the normal publish and close flow. Test events and announcements are marked TEST. After closure, the modal shows announcement delivery status; Retry Announcement uses saved placements. Discord links use the original HTTPS destination so the browser and operating system can handle opening Discord.

Player Information includes Guaranteed Seat and weighting from 0.1–10 for regular and test players. These organization/personal profile settings apply only to future draws, and players must still sign up. Event-specific settings can override a weight or guarantee a selected table during open signups.

Modal inputs use shared FormField defaults inside FormFields, which owns vertical spacing and floating-label clearance. Keep helper text with its field rather than adding individual margins.

Display Name overrides Discord names in app signup, assignment, and waitlist entries when set. Saving refreshes the list immediately; clearing restores the Discord name. Discord posts and saved lottery data retain Discord identities. Existing profile names are preserved.

Assigned event modals offer an Archive icon with shared Cancel/Confirm controls. Archived events are hidden from the default list; Show Archived includes them again with saved placements and waitlists.

Settings → Preferences groups player weight and guarantee options under Player Management, followed by Discord options. Timezone is first, above both sections. All boolean options default on for a new organization or personal workspace; explicit saved opt-outs remain off. Checkboxes and timezone changes autosave without a Save button. Organization editors can view settings; only admins can change shared options.

The Discord connection controls offer Disconnect with confirmation. Disconnect hides server/channel controls until authorization succeeds again. Preferences remains accessible without a connection. The Refresh Channels icon beside Signup Channel reloads eligible channels without leaving Settings.

The event list toolbar searches titles case-insensitively and sorts by title, event date, or creation datetime in either direction. Event date ascending is the default; search and sort respect Show Archived. Older events without a recorded creation time sort after dated records. The sort icon reflects direction.

## UI references

Major sections, controls, and dialogs have descriptive HTML `id` attributes for referring to the interface in issues and change requests. Find them with the browser's Inspect command; they are not visible labels. Keep these IDs stable when changing styling. Use record IDs for repeated controls and keep IDs unique in the rendered document. Existing labels and ARIA references must continue to point to their fields and headings.

| Area | Example IDs |
| --- | --- |
| Top bar | `site-header`, `site-title`, `active-organization`, `profile-menu-button` |
| Profile menu | `profile-players-link`, `profile-settings-link`, `profile-logout-button` |
| Events | `events-dashboard`, `events-search`, `events-sort-button`, `event-create-button`, `events-refresh-button`, `events-show-archived` |
| Event details | `event-open-{eventId}`, `event-dialog-{eventId}`, `event-close-{eventId}` |
| Event actions | `event-publish-{eventId}`, `event-edit-{eventId}`, `event-delete-{eventId}`, `event-archive-{eventId}`, `event-share-{eventId}`, `event-download-{eventId}` |
| Event form | `event-form`, `event-form-title`, `event-add-table-button`, `event-save-button`, `event-save-template-button` |
| Table controls | `event-{eventId}-table-{number}-add-player`, `event-{eventId}-table-{number}-player-remove-{playerId}` |
| Player lookup | `player-lookup`, `player-lookup-search`, `player-lookup-sort-guaranteed_seat`, `player-open-{playerId}` |
| Player information | `player-profile-dialog-{playerId}`, `player-display-name-{playerId}`, `player-weight-{playerId}`, `player-guaranteed-seat-{playerId}` |
| Settings tabs | `settings-preferences-tab`, `settings-connection-tab`, `settings-organization-tab` |
| Discord settings | `discord-connect-button`, `discord-server-select`, `discord-channel-select`, `discord-settings-save-button` |
| Preferences | `assignment-auto-weights`, `assignment-announce-changes`, `assignment-thread-updates`, `general-timezone`, `general-dm-waitlist-promotions` |
| Organization | `organization-select`, `organization-create-button`, `organization-delete-button`, `organization-add-user-button` |
| Organization members | `organization-member-{userId}`, `organization-member-role-{userId}`, `organization-member-delete-{userId}` |
| Confirmation | `organization-delete-dialog`, `organization-delete-dialog-cancel`, `organization-delete-dialog-confirm`; other confirmation controls also use their dialog ID plus `-cancel`, `-confirm`, or `-close` |
| Footer | `site-footer`, `footer-github-link` |

New table rows default to Table #1, Table #2, and so on, with Name and Capacity labels. Clicking or focusing a Name field selects its contents for replacement. New defaults avoid collisions with existing table names.

The create form actions use save icons with Draft (Schedule for recurring events), Template, and Cancel, and stay on one row on mobile.

The footer has a top divider and a single GitHub repository icon link, using the compact rounded icon style from Tiny Grimoire. The full-width settings page opens Preferences first, followed by Connection and Organization tabs. Timezone appears above the Player Management and Discord sections, with dividers between checkbox options. Organization uses an inline Active Organization selector. Organization deletion requires confirmation, and member removal uses a trash icon with an accessible username label.

Event process buttons share the 46px primary action height. Icon actions and modal close buttons are square at 46×46px. The event toolbar wraps on narrow screens, uses a Discord icon for the signup link, and relies on automatic signup polling rather than a toolbar refresh button.

All modal headers use ModalHeader to fit their title onto one line beside the square close button. Badges shrink more aggressively than the title so their text remains smaller. Titles refit when their text, available width, or fonts change, including after resizing an open dialog. Keep new modal headers on the shared component rather than implementing separate sizing logic.

Active assigned events offer Add Player for known players who are not already seated. The backend saves the placement as a manual override and keeps the original lottery snapshot/result unchanged. New additions can overfill a table, join the event thread, and queue a refresh of the existing Discord assignment posts. The Discord announcement preference controls separate table-change notices; roster edits are queued regardless. Previously withdrawn players can be re-added explicitly. Assigned, verification, and open-signup edits use the shared table-specific player-edit service; removing one table membership preserves other selections.

On mobile, event-detail date labels and values appear inline with a colon, labels aligned left and timestamps aligned right. All date rows share one fitted font size so they stay consistent and do not wrap. Desktop keeps labels stacked above values at the standard font size. Timestamps omit timezone abbreviations.


Preferences → Timezone persists an IANA timezone for the selected organization or personal workspace. Default (<current timezone>) follows the browser timezone; organization admins control shared settings. The setting applies to event lists/details, shared assignment pages, event date entry, recurring schedules, and PDF exports. Changing display timezone does not alter existing event instants or an existing series’ recurrence timezone. Date entry rejects nonexistent or repeated wall times at daylight-saving transitions. Discord continues rendering its timestamp markup in each viewer’s own timezone.

The timezone preference adds a nullable column to assignment_preferences; run the normal Alembic upgrade to head before starting a backend without local automatic migrations.

Preferences → Discord → Send private messages for waitlist promotions defaults on in new organizations and personal workspaces. It is independent of Announce table changes. Each DM includes Give up my seat for the intended recipient to withdraw directly in Discord. Initial draw placements and test users do not receive promotion DMs.

`features/settings/GeneralSettings.tsx` renders Preferences, using the shared `lib/generalSettings.ts` values/defaults contract. Existing API paths and control IDs remain stable. The event form uses `useEventTimes` for a single start wall-clock state and end override shared by desktop and mobile pickers. The end continues to follow the start by four elapsed hours until explicitly edited; raw wall times remain available to DST validation.

The Download all event signups control is intentionally hidden. Its download handler, CSV generation, and API endpoint remain available for a future UI location.

Public shared assignment pages include attendance checkboxes for seated and waitlisted players. Checking a player highlights their box in green. Entries are saved in local storage for that public link and browser; they survive refreshes and follow the player across table moves, waitlist promotions, and display-name changes. They do not edit assignments or sync to other browsers. A save failure leaves edits usable for the current page and displays a warning. Cross-viewer sync is tracked in #218.

Player and account names in roster rows, waitlists, player lookup columns, profile details, linked-player options, add/swap search results, and organization member lists stay on one line and show an ellipsis when space runs out. The full name remains in the DOM for accessibility, in the hover title, and in editable fields; sorting and searches use the full value. Shared `.truncate-name` styling controls this behavior. Name-based modal titles use ellipses rather than shrinking their font.
