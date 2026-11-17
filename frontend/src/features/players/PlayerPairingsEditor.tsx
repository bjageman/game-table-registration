import { matchesPlayer, type PlayerSummary } from "../../lib/players";
import { useEffect, useRef, useState } from "react";
import Autocomplete from "@mui/material/Autocomplete";
import { FormField } from "../../components/FormFields";
import { api, errorMessage, mutationOptions } from "../../lib/api";

export interface PairedPlayer { id: string; name: string }
export default function PlayerPairingsEditor({ playerId, pairings, csrf, readOnly = false, onChanged, onBusy, onAccessError, onError }: {
  playerId: string; pairings: PairedPlayer[]; csrf: string;
  readOnly?: boolean;
  onError?: (message: string) => void;
  onChanged: (pairings: PairedPlayer[]) => void; onBusy: (busy: boolean) => void;
  onAccessError: (error: unknown) => boolean;
}) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [reset, setReset] = useState(0);
  const [candidates, setCandidates] = useState<PlayerSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inFlight = useRef(false);
  useEffect(() => {
    if (!open || readOnly) return;
    const controller = new AbortController();
    api<PlayerSummary[]>("/players", { signal: controller.signal }).then((players) => {
      if (!controller.signal.aborted) setCandidates(players);
    }).catch((failure) => {
      if (!controller.signal.aborted && !onAccessError(failure)) {
        const message = errorMessage(failure);
        setError(message); onError?.(message);
      }
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [open, readOnly, onAccessError, onError]);
  const options = candidates.filter((candidate) => candidate.discord_id !== playerId).map((candidate) => ({
    id: candidate.discord_id, name: candidate.real_name || candidate.discord_name, source: candidate,
  }));
  async function save(values: PairedPlayer[]) {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setOpen(false); onBusy(true); setError(""); onError?.("");
    try {
      const result = await api<{ profile: { pairings: PairedPlayer[] } }>(`/players/${encodeURIComponent(playerId)}/pairings`, {
        ...mutationOptions(csrf, { player_ids: values.map((value) => value.id) }), method: "PUT",
      });
      onChanged(result.profile.pairings);
    } catch (failure) {
      if (!onAccessError(failure)) {
        const message = errorMessage(failure);
        setError(message); onError?.(message);
      }
    }
    finally { setReset((value) => value + 1); inFlight.current = false; setBusy(false); onBusy(false); }
  }
  return <div onKeyDown={(event) => event.stopPropagation()}>
    <Autocomplete<PairedPlayer & { source?: PlayerSummary }, true>
      multiple filterSelectedOptions
      key={reset} id={`player-pair-${playerId}`} fullWidth disablePortal openOnFocus
      options={[...options, ...pairings.filter((value) => !options.some((option) => option.id === value.id))]} value={pairings} loading={loading} disabled={busy || readOnly} open={open}
      onOpen={() => { setOpen(true); setLoading(true); setError(""); onError?.(""); }} onClose={() => setOpen(false)}
      getOptionLabel={(option) => option.name} isOptionEqualToValue={(option, value) => option.id === value.id}
      filterOptions={(items, state) => items.filter((item) => matchesPlayer(item.source ?? { discord_id: item.id, discord_name: item.name, real_name: "" }, state.inputValue))}
      onChange={(_, value) => { void save(value); }}
      renderOption={(props, option) => {
        const { key, ...attributes } = props;
        return <li key={key} {...attributes}>{option.name} ({option.id})</li>;
      }}
      renderInput={(params) => <FormField {...params} label="Pairings"
        slotProps={{ ...params.slotProps, inputLabel: { ...params.slotProps.inputLabel, shrink: true } }} />} />
    {error && !onError && <p role="alert" className="error">{error}</p>}
  </div>;
}
