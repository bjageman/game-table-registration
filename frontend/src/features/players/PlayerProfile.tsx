import { MIN_WEIGHT, MAX_WEIGHT, parseWeightInput } from "../../lib/weightInput";
import useDialog from "../../hooks/useDialog";
import ModalHeader from "../../components/ModalHeader";
import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import Checkbox from "@mui/material/Checkbox";
import FormControlLabel from "@mui/material/FormControlLabel";
import FormFields, { FormField } from "../../components/FormFields";
import { api, errorMessage, mutationOptions } from "../../lib/api";
import { isBackdropClick } from "../../lib/dialogBackdrop";
import LoadingIndicator from "../../components/LoadingIndicator";
import type { PlayerSummary } from "../../lib/players";
import PlayerPairEditor, { type Partner } from "./PlayerPairEditor";

interface Profile extends PlayerSummary { weighting: number; is_test?: boolean; guaranteed_seat?: boolean; partner?: Partner | null; }
type ProfileChange = { real_name?: string; weighting?: number; guaranteed_seat?: boolean };

export default function PlayerProfile({ player, csrf, readOnly = false, onClose, onAccessError, onSaved }: {
  player: { id: string; name: string };
  csrf: string;
  readOnly?: boolean;
  onClose: () => void;
  onSaved?: () => void;
  onAccessError: (error: unknown) => boolean;
}) {
  const heading = `player-profile-heading-${player.id}`;
  const nameField = `player-display-name-${player.id}`;
  const profileRef = useRef<Profile | undefined>(undefined);
  const submitted = useRef({ real_name: "", weighting: 5, guaranteed_seat: false });
  const saveQueue = useRef<Promise<void>>(Promise.resolve());
  const pending = useRef(0);
  const failed = useRef(false);
  const closing = useRef(false);
  const pairingBusy = useRef(false);
  const pendingNames = useRef(0);
  const nameFeedbackTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [nameSaveFeedback, setNameSaveFeedback] = useState(false);
  const [profile, setProfile] = useState<Profile>();
  const [realName, setRealName] = useState("");
  const [weighting, setWeighting] = useState("5");
  const [guaranteedSeat, setGuaranteedSeat] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savingWeight, setSavingWeight] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [pairError, setPairError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const dialog = useDialog();
  useEffect(() => () => clearTimeout(nameFeedbackTimer.current), []);
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
  function saveChange(change: ProfileChange, message = ""): Promise<void> {
    Object.assign(submitted.current, change);
    pending.current += 1;
    setSaving(true); setError(""); setNotice("");
    if (change.real_name !== undefined) {
      pendingNames.current += 1;
      clearTimeout(nameFeedbackTimer.current);
      setNameSaveFeedback(true);
    }
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
        if (change.real_name !== undefined && pendingNames.current === 1) setNameSaveFeedback(false);
        failed.current = true;
        const current = profileRef.current;
        if (current) {
          if (change.real_name !== undefined && submitted.current.real_name === change.real_name) submitted.current.real_name = current.real_name;
          if (change.weighting !== undefined && submitted.current.weighting === change.weighting) submitted.current.weighting = current.weighting;
          if (change.guaranteed_seat !== undefined && submitted.current.guaranteed_seat === change.guaranteed_seat) submitted.current.guaranteed_seat = Boolean(current.guaranteed_seat);
        }
        if (!onAccessError(failure)) setError(errorMessage(failure));
      } finally {
        if (change.real_name !== undefined) {
          pendingNames.current -= 1;
          if (pendingNames.current === 0) nameFeedbackTimer.current = setTimeout(() => setNameSaveFeedback(false), 1500);
        }
        pending.current -= 1;
        if (pending.current === 0) setSaving(false);
      }
    });
    saveQueue.current = task;
    return task;
  }
  function saveName() {
    if (profileRef.current && realName !== submitted.current.real_name) {
      void saveChange({ real_name: realName });
    }
  }
  function saveGuarantee() {
    if (profileRef.current && guaranteedSeat !== submitted.current.guaranteed_seat) {
      void saveChange({ guaranteed_seat: guaranteedSeat });
    }
  }
  function saveWeight(): boolean {
    if (!profileRef.current) return true;
    const parsed = parseWeightInput(weighting);
    if (!parsed) {
      setError(`Choose a weighting from ${MIN_WEIGHT} to ${MAX_WEIGHT}.`);
      return false;
    }
    const { value, notice: message } = parsed;
    setWeighting(String(value));
    setError("");
    if (value === submitted.current.weighting) {
      setNotice(message);
      return true;
    }
    setSavingWeight(true);
    void saveChange({ weighting: value }, message).finally(() => setSavingWeight(false));
    return true;
  }
  async function close() {
    if (readOnly) { onClose(); return; }
    if (closing.current || pairingBusy.current) return;
    closing.current = true;
    failed.current = false;
    saveName();
    saveGuarantee();
    if (!saveWeight()) { closing.current = false; return; }
    await saveQueue.current;
    if (!failed.current) onClose();
    closing.current = false;
  }
  return <dialog id={`player-profile-dialog-${player.id}`} ref={dialog} aria-labelledby={heading} aria-busy={saving}
    onClick={(event) => { if (isBackdropClick(event)) void close(); }}
    onCancel={(event) => { event.preventDefault(); void close(); }}
    onKeyDown={(event) => {
      if (event.key === "Enter" && !(event.target instanceof HTMLButtonElement)) {
        event.preventDefault();
        void close();
      }
    }}>
    <ModalHeader className="player-profile-header">
      <h2 id={heading}>Player Information</h2>
      {nameSaveFeedback && <span className="profile-save-feedback"><LoadingIndicator label="Saving…" /></span>}
      {profile?.is_test && <span className="badge">Test User</span>}
      <button id={`player-profile-close-${player.id}`} type="button" aria-label="Close player information" title="Close" onClick={() => void close()} autoFocus><X size={18} aria-hidden="true" /></button>
    </ModalHeader>
    {error && <p role="alert" className="player-profile-feedback">{error}</p>}
    {pairError && <p role="alert" className="player-profile-feedback">{pairError}</p>}
    {notice && <p role="status" className="player-profile-feedback">{notice}</p>}
    {!profile && error && <button type="button" onClick={() => setAttempt((value) => value + 1)}>Retry</button>}
    <dl className="player-discord-name"><dt>Discord Name</dt><dd>{profile?.discord_name ?? player.name}</dd></dl>
    {!profile && !error && <p><LoadingIndicator label="Loading player information…" /></p>}
    {profile && <div aria-label="Player information">
      <FormFields>
      <FormField id={nameField} label="Display Name" value={realName} fullWidth disabled={readOnly}
        onChange={(event) => { setRealName(event.target.value); setNotice(""); }}
        onBlur={saveName}
        slotProps={{ htmlInput: { maxLength: 100 } }} />
      <div className="profile-weight-edit"><FormField id={`player-weight-${player.id}`} label="Global Weighting" type="number" value={weighting} fullWidth disabled={savingWeight || readOnly}
        onChange={(event) => { setWeighting(event.target.value); setNotice(""); }}
        onBlur={() => { saveWeight(); }}
        slotProps={{ htmlInput: { min: MIN_WEIGHT, max: MAX_WEIGHT, step: 0.1 } }} />
      </div>
      <PlayerPairEditor playerId={player.id} partner={profile.partner ?? null} csrf={csrf} readOnly={readOnly} onAccessError={onAccessError} onError={setPairError}
        onBusy={(busy) => { pairingBusy.current = busy; }} onChanged={(partner) => {
          setProfile((current) => current ? { ...current, partner } : current);
          onSaved?.();
        }} />
      <FormControlLabel label="Guaranteed Seat" control={<Checkbox id={`player-guaranteed-seat-${player.id}`} checked={guaranteedSeat} disabled={readOnly}
        onChange={(event) => { setGuaranteedSeat(event.target.checked); void saveChange({ guaranteed_seat: event.target.checked }); }} />} />
      </FormFields>

    </div>}
  </dialog>;
}
