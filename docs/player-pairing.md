# Paired Player Preferences

Preferences, profiles, weights, guarantees, display names, and test identities belong to the selected organization or personal workspace, additionally scoped by Discord server. Organizations sharing a server do not share these settings.

## Editing preferences

Player Information has a searchable, unordered multi-player **Paired Player Preferences** field, replacing Linked Player. Adding Alice → Bob also adds Bob → Alice. Adding Alice → Carol does not add Bob → Carol. Removing a preference removes the same edge from both players, preserving all their other preferences. Multiple organizers' changes are serialized within the profile scope.

PUT `/api/players/{id}/preferences` accepts `{ "player_ids": ["other-id", ...] }` and replaces that player's direct preferences. An empty list removes them all. IDs must refer to known players in the same organization/workspace and server; self-preferences are rejected and duplicates are ignored. Moderator access and CSRF protection are required. Read-only members can view preferences.

## Draws

1. The individual weighted lottery (`-ln(U)/weight`) and each player's own guarantees select the seated players. Preferences cannot change the winner set, lottery order, or waitlist order. A guaranteed seat never extends to a preferred player.
2. Among those winners, try to improve the number of direct preferences seated at the same table. Respect selected tables, capacities, and individual table guarantees. Partial matches are allowed; incompatible preferences leave winners seated separately.

For example, if Alice prefers Bob, Carl, and David, but only Alice and David win seats, they can sit together while Bob and Carl remain waitlisted. A player with one guaranteed seat and one companion can still take the last available seat alone.

The deterministic, best-effort placement pass tries unmatched direct pairs at shared tables, reserves their seats, and uses capacity-aware matching to retain every other winner. A proposed arrangement is accepted only when it increases the total number of satisfied direct edges. Earlier lottery priorities break processing ties. Overlapping preferences do not become mandatory transitive groups. Optional optimization stops after 1,000 candidate arrangements; it does not promise a globally optimal grouping.

Preferences are frozen when closing begins and recorded in the immutable draw snapshot with its seed and algorithm version (`preference-weighted-matching-v6`). Later profile edits affect future draws only. Automatic promotions follow the individual saved waitlist order and do not pull additional preferred players into seats. Manual changes affect only the selected player.

## Migration and historical draws

Existing reciprocal Linked Player pairs become preference edges, preserving their organization/workspace and server scope. The old profile partner column is removed. Downgrading can represent only disjoint pairs and retains a deterministic subset of multi-player preferences.

Historical snapshots containing `pairs` retain the previous allocator and promotion behavior for replay and existing rosters. An already-started close with frozen legacy pairs also finishes using those rules. New draws use the individual-winners-first preference behavior above. Existing saved draws are never rewritten.
