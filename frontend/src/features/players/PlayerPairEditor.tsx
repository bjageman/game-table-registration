import { useEffect, useRef, useState } from "react";
import Autocomplete from "@mui/material/Autocomplete";
import { FormField } from "../../components/FormFields";
import ConfirmationDialog from "../../components/ConfirmationDialog";
import { api, errorMessage, mutationOptions } from "../../lib/api";

export interface Partner { id: string; name: string }
interface Candidate { discord_id: string; discord_name: string; real_name: string }
type PairResponse = { profile: { partner: Partner | null } } | {
  confirmation_required: true; replace_partner_id: string; message: string;
};

export default function PlayerPairEditor({ playerId, partner, csrf, readOnly = false, onChanged, onBusy, onAccessError, onError }: {
  playerId: string; partner: Partner | null; csrf: string;
  readOnly?: boolean;
  onError?: (message: string) => void;
  onChanged: (partner: Partner | null) => void; onBusy: (busy: boolean) => void;
  onAccessError: (error: unknown) => boolean;
}) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [reset, setReset] = useState(0);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirmation, setConfirmation] = useState<{ target: string; previous: string; message: string }>();
  const inFlight = useRef(false);
  useEffect(() => {
    if (!open || readOnly) return;
    const controller = new AbortController();
    api<Candidate[]>("/players", { signal: controller.signal }).then((players) => {
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
    id: candidate.discord_id, name: candidate.real_name || candidate.discord_name, discordName: candidate.discord_name,
  }));
  async function link(target: string | null, previous?: string) {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setOpen(false); onBusy(true); setError(""); onError?.("");
    try {
      const result = await api<PairResponse>(`/players/${encodeURIComponent(playerId)}/partner`, {
        ...mutationOptions(csrf, { partner_id: target, replace_partner_id: previous ?? null }), method: "PUT",
      });
      if ("confirmation_required" in result) {
        setConfirmation({ target: target!, previous: result.replace_partner_id, message: result.message });
      } else {
        onChanged(result.profile.partner);
        setConfirmation(undefined); setReset((value) => value + 1);
      }
    } catch (failure) {
      setReset((value) => value + 1);
      if (!onAccessError(failure)) {
        const message = errorMessage(failure);
        setError(message);
        if (!confirmation) onError?.(message);
      }
    }
    finally { inFlight.current = false; setBusy(false); onBusy(false); }
  }
  return <div onKeyDown={(event) => event.stopPropagation()}>
    <Autocomplete<Partner & { discordName?: string }>
      key={`${partner?.id ?? "none"}:${reset}`} id={`player-pair-${playerId}`} fullWidth disablePortal openOnFocus
      options={options} value={partner} loading={loading} disabled={busy || readOnly} open={open}
      onOpen={() => { setOpen(true); setLoading(true); setError(""); onError?.(""); }} onClose={() => setOpen(false)}
      getOptionLabel={(option) => option.name} isOptionEqualToValue={(option, value) => option.id === value.id}
      filterOptions={(items, state) => items.filter((item) => `${item.name} ${item.discordName ?? ""} ${item.id}`
        .toLocaleLowerCase().includes(state.inputValue.trim().toLocaleLowerCase()))}
      onChange={(_, value) => { if (value?.id !== partner?.id) void link(value?.id ?? null); }}
      renderOption={(props, option) => {
        const { key, ...attributes } = props;
        return <li key={key} {...attributes}>{option.name} ({option.id})</li>;
      }}
      renderInput={(params) => <FormField {...params} label="Linked Player"
        slotProps={{ ...params.slotProps, inputLabel: { ...params.slotProps.inputLabel, shrink: true } }} />} />
    {error && !confirmation && !onError && <p role="alert" className="error">{error}</p>}
    {confirmation && <ConfirmationDialog id={`player-pair-confirm-${playerId}`} title="Replace player link?" busy={busy} error={error}
      onCancel={() => { setConfirmation(undefined); setReset((value) => value + 1); setError(""); }}
      onConfirm={() => void link(confirmation.target, confirmation.previous)}>
      <p>{confirmation.message}</p>
    </ConfirmationDialog>}
  </div>;
}
