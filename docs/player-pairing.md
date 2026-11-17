# Pairings

Pairings, profiles, weights, guarantees, display names, and test identities belong to the selected organization or personal workspace, additionally scoped by Discord server. Organizations sharing a server do not share these settings.

## Editing pairings

Player Information has a searchable, unordered multi-player **Pairings** field, replacing Linked Player. Adding Alice → Bob also adds Bob → Alice. Adding Alice → Carol does not add Bob → Carol. Removing a pairing removes the same edge from both players, preserving all their other pairings. Multiple organizers' changes are serialized within the profile scope.

PUT `/api/players/{id}/pairings` accepts `{ "player_ids": ["other-id", ...] }` and replaces that player's direct pairings. An empty list removes them all. IDs must refer to known players in the same organization/workspace and server; self-pairings are rejected and duplicates are ignored. Moderator access and CSRF protection are required. Read-only members can view pairings.

## Draws

1. The individual weighted lottery (`-ln(U)/weight`) and each player's own guarantees select the seated players. Pairings cannot change the winner set, lottery order, or waitlist order. A guaranteed seat never extends to a paired player.
2. Among those winners, prioritize direct matches for players with shorter saved pairing lists, then improve matches for longer lists. A single-pairing match outranks any number of matches involving only players with longer lists. Respect selected tables, capacities, and individual table guarantees. Partial matches are allowed; incompatible pairings leave winners seated separately.

For example, if Alice prefers Bob, Carl, and David, but only Alice and David win seats, they can sit together while Bob and Carl remain waitlisted. A player with one guaranteed seat and one companion can still take the last available seat alone.

The deterministic, best-effort placement pass tries unmatched direct pairs at shared tables, reserves their seats, and uses capacity-aware matching to retain every other winner. A proposed arrangement is accepted only when it improves the counts of satisfied direct edges in ascending list-length priority. Each edge uses the shorter of its two players’ saved list lengths; absent or waitlisted players are never seated by this pass. Earlier lottery priorities break ties within a list-length priority. Overlapping pairings do not become mandatory transitive groups. Optional optimization stops after 1,000 candidate arrangements; it does not promise a globally optimal grouping.

Pairings are frozen when closing begins and recorded in the immutable draw snapshot with its seed and algorithm version (`preference-priority-matching-v7`). Later profile edits affect future draws only. Automatic promotions follow the individual saved waitlist order and do not pull additional paired players into seats. Manual changes affect only the selected player.

## Migration and historical draws

Existing reciprocal Linked Player pairs become pairing edges, preserving their organization/workspace and server scope. The old profile partner column is removed. Downgrading can represent only disjoint pairs and retains a deterministic subset of multi-player pairings.

Historical snapshots containing `pairs` retain the previous allocator and promotion behavior for replay and existing rosters. An already-started close with frozen legacy pairs also finishes using those rules. New draws use the individual-winners-first pairing behavior above. Existing saved draws are never rewritten.
