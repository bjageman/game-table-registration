import { useEffect, useId, useRef, useState } from "react";
import { X } from "lucide-react";
import Checkbox from "@mui/material/Checkbox";
import FormControlLabel from "@mui/material/FormControlLabel";
import FormFields, { FormField } from "../../components/FormFields";
import { api, errorMessage, mutationOptions } from "../../lib/api";
import { isBackdropClick } from "../../lib/dialogBackdrop";
import LoadingIndicator from "../../components/LoadingIndicator";

interface Profile { discord_id: string; discord_name: string; real_name: string; weighting: number; is_test?: boolean; guaranteed_seat?: boolean; }
type ProfileChange = { real_name?: string; weighting?: number; guaranteed_seat?: boolean };

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
  const profileRef = useRef<Profile | undefined>(undefined);
  const submitted = useRef({ real_name: "", weighting: 1, guaranteed_seat: false });
  const saveQueue = useRef<Promise<void>>(Promise.resolve());
  const pending = useRef(0);
  const failed = useRef(false);
  const closing = useRef(false);
  const [profile, setProfile] = useState<Profile>();
  const [realName, setRealName] = useState("");
  const [weighting, setWeighting] = useState("1");
  const [guaranteedSeat, setGuaranteedSeat] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savingWeight, setSavingWeight] = useState(false);
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
    api<Profile>(`/players/${encodeURIComponent(player.id)}?signup_name=${encodeURIComponent(player.name)}`, { signal: controller.signal })
      .then((value) => {
        if (!controller.signal.aborted) {
          profileRef.current = value;
          submitted.current = { real_name: value.real_name, weighting: value.weighting, guaranteed_seat: Boolean(value.guaranteed_seat) };
          setProfile(value); setRealName(value.real_name); setWeighting(String(value.weighting)); setGuaranteedSeat(Boolean(value.guaranteed_seat)); setError("");
        }
      })
      .catch((failure) => { if (!controller.signal.aborted && !onAccessError(failure)) setError(errorMessage(failure)); });
    return () => controller.abort();
  }, [player.id, player.name, attempt, onAccessError]);
  function saveChange(change: ProfileChange, message: string): Promise<void> {
    Object.assign(submitted.current, change);
    pending.current += 1;
    setSaving(true); setError(""); setNotice("");
    const task = saveQueue.current.then(async () => {
      try {
        const updated = await api<Profile>(`/players/${encodeURIComponent(player.id)}`, {
          ...mutationOptions(csrf, change), method: "PUT",
        });
        profileRef.current = updated;
        setProfile(updated);
        if (change.real_name !== undefined) {
          setRealName((current) => current === change.real_name ? updated.real_name : current);
          if (submitted.current.real_name === change.real_name) submitted.current.real_name = updated.real_name;
        }
        if (change.weighting !== undefined) {
          setWeighting((current) => Number(current) === change.weighting ? String(updated.weighting) : current);
          if (submitted.current.weighting === change.weighting) submitted.current.weighting = updated.weighting;
        }
        if (change.guaranteed_seat !== undefined) {
          setGuaranteedSeat((current) => current === change.guaranteed_seat ? Boolean(updated.guaranteed_seat) : current);
          if (submitted.current.guaranteed_seat === change.guaranteed_seat) submitted.current.guaranteed_seat = Boolean(updated.guaranteed_seat);
        }
        setNotice(message);
        onSaved?.();
      } catch (failure) {
        failed.current = true;
        const current = profileRef.current;
        if (current) {
          if (change.real_name !== undefined && submitted.current.real_name === change.real_name) submitted.current.real_name = current.real_name;
          if (change.weighting !== undefined && submitted.current.weighting === change.weighting) submitted.current.weighting = current.weighting;
          if (change.guaranteed_seat !== undefined && submitted.current.guaranteed_seat === change.guaranteed_seat) submitted.current.guaranteed_seat = Boolean(current.guaranteed_seat);
        }
        if (!onAccessError(failure)) setError(errorMessage(failure));
      } finally {
        pending.current -= 1;
        if (pending.current === 0) setSaving(false);
      }
    });
    saveQueue.current = task;
    return task;
  }
  function saveName() {
    if (profileRef.current && realName !== submitted.current.real_name) {
      void saveChange({ real_name: realName }, "Display name saved.");
    }
  }
  function saveGuarantee() {
    if (profileRef.current && guaranteedSeat !== submitted.current.guaranteed_seat) {
      void saveChange({ guaranteed_seat: guaranteedSeat }, "Guaranteed seat saved.");
    }
  }
  function saveWeight(): boolean {
    if (!profileRef.current) return true;
    const value = Number(weighting);
    if (!weighting.trim() || !Number.isFinite(value) || value < 0.1 || value > 10) {
      setError("Choose a weighting from 0.1 to 10.");
      return false;
    }
    if (value === submitted.current.weighting) {
      return true;
    }
    setSavingWeight(true);
    void saveChange({ weighting: value }, "Global weighting saved.").finally(() => setSavingWeight(false));
    return true;
  }
  async function close() {
    if (closing.current) return;
    closing.current = true;
    failed.current = false;
    saveName();
    saveGuarantee();
    if (!saveWeight()) { closing.current = false; return; }
    await saveQueue.current;
    if (!failed.current) onClose();
    closing.current = false;
  }
  return <dialog ref={dialog} aria-labelledby={heading} aria-busy={saving}
    onClick={(event) => { if (isBackdropClick(event)) void close(); }}
    onCancel={(event) => { event.preventDefault(); void close(); }}
    onKeyDown={(event) => {
      if (event.key === "Enter" && !(event.target instanceof HTMLButtonElement)) {
        event.preventDefault();
        void close();
      }
    }}>
    <div className="event-modal-header player-profile-header">
      <h2 id={heading}>Player Information</h2>
      {profile?.is_test && <span className="badge">Test User</span>}
      <button type="button" aria-label="Close player information" title="Close" onClick={() => void close()} autoFocus><X size={18} aria-hidden="true" /></button>
    </div>
    <dl className="player-discord-name"><dt>Discord Name</dt><dd>{profile?.discord_name ?? player.name}</dd></dl>
    {!profile && !error && <p><LoadingIndicator label="Loading player information…" /></p>}
    {error && <p role="alert" className="error">{error}</p>}
    {!profile && error && <button type="button" onClick={() => setAttempt((value) => value + 1)}>Retry</button>}
    {profile && <div aria-label="Player information">
      <FormFields>
      <FormField id={nameField} label="Display Name" value={realName} fullWidth
        onChange={(event) => { setRealName(event.target.value); setNotice(""); }}
        onBlur={saveName}
        slotProps={{ htmlInput: { maxLength: 100 } }} />
      <div className="profile-weight-edit"><FormField label="Global Weighting" type="number" value={weighting} fullWidth disabled={savingWeight}
        onChange={(event) => { setWeighting(event.target.value); setNotice(""); }}
        onBlur={() => { saveWeight(); }}
        slotProps={{ htmlInput: { min: 0.1, max: 10, step: 0.1 } }} />
      </div>
      <FormControlLabel label="Guaranteed Seat" control={<Checkbox checked={guaranteedSeat}
        onChange={(event) => { setGuaranteedSeat(event.target.checked); void saveChange({ guaranteed_seat: event.target.checked }, "Guaranteed seat saved."); }} />} />
      {notice && <p role="status">{notice}</p>}
      </FormFields>
    </div>}
  </dialog>;
}
