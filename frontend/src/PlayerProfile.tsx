import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { X } from "lucide-react";
import Checkbox from "@mui/material/Checkbox";
import FormControlLabel from "@mui/material/FormControlLabel";
import FormFields, { FormField } from "./FormFields";
import { api, errorMessage, mutationOptions } from "./api";
import { isBackdropClick } from "./dialogBackdrop";

interface Profile { discord_id: string; discord_name: string; real_name: string; weighting: number; is_test?: boolean; guaranteed_seat?: boolean; }

export default function PlayerProfile({ player, csrf, onClose, onAccessError, onSaved }: {
  player: { id: string; name: string };
  csrf: string;
  onClose: () => void;
  onSaved?: () => void;
  onAccessError: (error: unknown) => boolean;
}) {
  const heading = useId();
  const nameField = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  const inFlight = useRef(false);
  const [profile, setProfile] = useState<Profile>();
  const [realName, setRealName] = useState("");
  const [weighting, setWeighting] = useState("1");
  const [guaranteedSeat, setGuaranteedSeat] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const modal = dialog.current;
    const trigger = document.activeElement;
    modal?.showModal();
    return () => { modal?.close(); if (trigger instanceof HTMLElement && trigger.isConnected) trigger.focus(); };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    api<Profile>(`/players/${encodeURIComponent(player.id)}`, { signal: controller.signal })
      .then((value) => {
        if (!controller.signal.aborted) { setProfile(value); setRealName(value.real_name); setWeighting(String(value.weighting)); setGuaranteedSeat(Boolean(value.guaranteed_seat)); setError(""); }
      })
      .catch((failure) => { if (!controller.signal.aborted && !onAccessError(failure)) setError(errorMessage(failure)); });
    return () => controller.abort();
  }, [player.id, attempt, onAccessError]);
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!profile || inFlight.current) return;
    if (profile.is_test && (!weighting.trim() || !Number.isFinite(Number(weighting)) || Number(weighting) < 0.1 || Number(weighting) > 10)) {
      setError("Choose a weighting from 0.1 to 10."); return;
    }
    inFlight.current = true;
    setSaving(true); setError(""); setNotice("");
    try {
      const value = await api<Profile>(`/players/${encodeURIComponent(player.id)}`, {
        ...mutationOptions(csrf, { real_name: realName, guaranteed_seat: guaranteedSeat, ...(profile.is_test ? { weighting: Number(weighting) } : {}) }), method: "PUT",
      });
      setProfile(value); setRealName(value.real_name); setWeighting(String(value.weighting)); setGuaranteedSeat(Boolean(value.guaranteed_seat)); setNotice("Player information saved.");
      onSaved?.();
    } catch (failure) {
      if (!onAccessError(failure)) setError(errorMessage(failure));
    } finally { inFlight.current = false; setSaving(false); }
  }
  return <dialog ref={dialog} aria-labelledby={heading} aria-busy={saving}
    onClick={(event) => { if (!inFlight.current && isBackdropClick(event)) onClose(); }}
    onCancel={(event) => { event.preventDefault(); if (!inFlight.current) onClose(); }}>
    <div className="event-modal-header">
      <h2 id={heading}>Player Information</h2>
      {profile?.is_test && <span className="badge">Test User</span>}
      <button type="button" aria-label="Close player information" title="Close" disabled={saving} onClick={onClose} autoFocus><X size={18} aria-hidden="true" /></button>
    </div>
    <dl className="player-discord-name"><dt>Discord Name</dt><dd>{profile?.discord_name ?? player.name}</dd></dl>
    {!profile && !error && <p role="status">Loading player information…</p>}
    {error && <p role="alert" className="error">{error}</p>}
    {!profile && error && <button type="button" onClick={() => setAttempt((value) => value + 1)}>Retry</button>}
    {profile && <form onSubmit={(event) => void save(event)} aria-label="Player information">
      <FormFields>
      <FormField id={nameField} label="Display Name" value={realName} fullWidth disabled={saving}
        onChange={(event) => { setRealName(event.target.value); setNotice(""); }}
        slotProps={{ htmlInput: { maxLength: 100 } }} />
      {profile.is_test ? <FormField label="Current Weighting" type="number" value={weighting} fullWidth disabled={saving}
        onChange={(event) => { setWeighting(event.target.value); setNotice(""); }}
        slotProps={{ htmlInput: { min: 0.1, max: 10, step: "any" } }} />
        : <div><dl><dt>Current Weighting</dt><dd>{profile.weighting.toFixed(1)}</dd></dl>
</div>}
      <FormControlLabel label="Guaranteed Seat" control={<Checkbox checked={guaranteedSeat} disabled={saving}
        onChange={(event) => { setGuaranteedSeat(event.target.checked); setNotice(""); }} />} />
      {notice && <p role="status">{notice}</p>}
      <div className="form-actions confirmation-actions"><button type="submit" className="primary" disabled={saving}>{saving ? "Saving…" : "Save"}</button></div>
      </FormFields>
    </form>}
  </dialog>;
}
