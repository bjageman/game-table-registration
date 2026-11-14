import { useEffect, useRef, useState } from "react";
import ConfirmationDialog from "../../components/ConfirmationDialog";
import { api, errorMessage, mutationOptions } from "../../lib/api";

export interface Partner { id: string; name: string }
interface Candidate { discord_id: string; discord_name: string; real_name: string }
type PairResponse = { profile: { partner: Partner | null } } | {
  confirmation_required: true; replace_partner_id: string; message: string;
};

export default function PlayerPairEditor({ playerId, partner, csrf, readOnly = false, onChanged, onBusy, onAccessError }: {
  playerId: string; partner: Partner | null; csrf: string;
  readOnly?: boolean;
  onChanged: (partner: Partner | null) => void; onBusy: (busy: boolean) => void;
  onAccessError: (error: unknown) => boolean;
}) {
  const [query, setQuery] = useState("");
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirmation, setConfirmation] = useState<{ target: string; previous: string; message: string }>();
  const inFlight = useRef(false);
  useEffect(() => {
    if (query.trim().length < 2) return;
    const controller = new AbortController();
    api<Candidate[]>("/players", { signal: controller.signal }).then((players) => {
      if (!controller.signal.aborted) setCandidates(players);
    }).catch((failure) => {
      if (!controller.signal.aborted && !onAccessError(failure)) setError(errorMessage(failure));
    });
    return () => controller.abort();
  }, [query, onAccessError]);
  const normalized = query.trim().toLocaleLowerCase();
  const visible = candidates.filter((candidate) => candidate.discord_id !== playerId && candidate.discord_id !== partner?.id
    && `${candidate.discord_name} ${candidate.real_name} ${candidate.discord_id}`.toLocaleLowerCase().includes(normalized));
  async function link(target: string | null, previous?: string) {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); onBusy(true); setError("");
    try {
      const result = await api<PairResponse>(`/players/${encodeURIComponent(playerId)}/partner`, {
        ...mutationOptions(csrf, { partner_id: target, replace_partner_id: previous ?? null }), method: "PUT",
      });
      if ("confirmation_required" in result) {
        setConfirmation({ target: target!, previous: result.replace_partner_id, message: result.message });
      } else {
        onChanged(result.profile.partner);
        setQuery(""); setCandidates([]); setConfirmation(undefined);
      }
    } catch (failure) { if (!onAccessError(failure)) setError(errorMessage(failure)); }
    finally { inFlight.current = false; setBusy(false); onBusy(false); }
  }
  return <section aria-label="Linked player" onKeyDown={(event) => event.stopPropagation()}>
    <h3>Linked player</h3>
    <p className="help">Applies to future draws in this organization when both players sign up. Manual edits affect only the selected player.</p>
    {partner ? <p>Linked to {partner.name} {!readOnly && <button type="button" disabled={busy} onClick={() => void link(null)}>Unlink player</button>}</p> : <p>No linked player.</p>}
    {!readOnly && <>
    <label htmlFor={`player-pair-search-${playerId}`}>Search for a player to link</label>
    <input id={`player-pair-search-${playerId}`} type="search" value={query} disabled={busy} placeholder="Name or Discord ID"
      onChange={(event) => { setQuery(event.target.value); setCandidates([]); setError(""); }} />
    {normalized.length >= 2 && <ul className="add-player-results" aria-label="Matching players">
      {visible.map((candidate) => <li key={candidate.discord_id}><button type="button" disabled={busy}
        onClick={() => void link(candidate.discord_id)}>Link {candidate.real_name || candidate.discord_name} ({candidate.discord_id})</button></li>)}
    </ul>}
    {error && !confirmation && <p role="alert" className="error">{error}</p>}
    {confirmation && <ConfirmationDialog id={`player-pair-confirm-${playerId}`} title="Replace player link?" busy={busy} error={error}
      onCancel={() => { setConfirmation(undefined); setError(""); }} onConfirm={() => void link(confirmation.target, confirmation.previous)}>
      <p>{confirmation.message}</p>
    </ConfirmationDialog>}
    </>}
  </section>;
}
