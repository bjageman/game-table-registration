# Player pairing

Player profiles, weights, guarantees, display names, test-player identities, and links belong to the selected organization. Personal events use the signed-in account's own profile scope. Sharing a Discord server does not share profiles between organizations.

## Links

An organizer can search for another known player in Player Information. A link is reciprocal and each player can have one partner. Unlinking clears both profiles. Changing Alice from Bob to Carol clears Bob's link. If Carol is already linked to Dave, the organizer must confirm breaking Carol and Dave's link before saving. Confirmation is repeated if Carol's partner changes in the meantime.

Links are frozen when closing signups begins and saved in the draw snapshot. Changing profiles later affects future draws only. Manual assignment changes affect only the player selected by the organizer. A seated player's withdrawal does not remove their partner.

## Draws

- If only one partner signs up, that player participates normally.
- If both sign up but have no table choices in common, they participate independently for that event; the profile link remains saved.
- A pair receives one random priority using the average of its members' effective weights. Each player's later weight adjustment applies to their own weight.
- Shared eligible tables are attempted first. If shared seating is unavailable, both players may be seated at separate eligible tables.
- A placement accepts both members or neither. When only one member could be seated, both are waitlisted. A single player can use a remaining seat.
- Either member's guaranteed-seat flag extends to the pair for that draw, without changing the other member's profile. Guaranteed pairs cannot automatically split across tables.
- Conflicting table guarantees or insufficient capacity for a guaranteed pair leave both members waitlisted and show an organizer alert. Existing individual guarantees are honored before attempting inherited pair guarantees. An organizer resolves the pair conflict with manual edits; it does not abort everyone else's draw.

The paired allocator uses deterministic augmenting placements, keeps previously accepted groups seated, and bounds exploration by visiting each group once per insertion. Draws with no active pairs retain the existing individual matching algorithm. The saved seed, snapshot, and algorithm version allow replay.

## Automatic promotions

Automatic promotions use the links saved in the draw, not current profile links. A waiting pair needs seats for both members. A single player behind a pair can take a lone vacancy. When both members can be promoted, both receive promotion notices with their actual destination tables. Guarantee conflicts remain for organizer intervention. Manual additions never automatically move the linked player.

## Existing profiles

The migration converts existing server-wide profiles into independent copies for existing organization and personal scopes associated with that server, preserving saved settings. No rows are shared and subsequent edits never propagate between scopes. New organizations start with fresh profiles and no links. Historical draw snapshots remain unchanged.

The downgrade can represent only one profile per server/player; it picks a deterministic copy because the older schema cannot store independent organization profiles.
