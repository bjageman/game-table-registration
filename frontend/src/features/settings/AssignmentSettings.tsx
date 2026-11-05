import { useEffect, useRef, useState, type FormEvent } from "react";
import Checkbox from "@mui/material/Checkbox";
import FormControlLabel from "@mui/material/FormControlLabel";
import { api, errorMessage, mutationOptions } from "../../lib/api";
import LoadingIndicator from "../../components/LoadingIndicator";

interface Settings { automatic_weight_adjustment: boolean; announce_table_changes: boolean; }

export default function AssignmentSettings({ csrf, restricted = false, onAccessError }: {
  csrf: string; restricted?: boolean; onAccessError: (error: unknown) => boolean;
}) {
  const [enabled, setEnabled] = useState(true);
  const [announceChanges, setAnnounceChanges] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const inFlight = useRef(false);
  useEffect(() => {
    const controller = new AbortController();
    api<Settings>("/settings/assignment", { signal: controller.signal }).then((value) => {
      if (!controller.signal.aborted) { setEnabled(value.automatic_weight_adjustment); setAnnounceChanges(value.announce_table_changes); setLoaded(true); setError(""); }
    }).catch((failure) => { if (!controller.signal.aborted && !onAccessError(failure)) setError(errorMessage(failure)); });
    return () => controller.abort();
  }, [attempt, onAccessError]);
  async function save(event: FormEvent) {
    event.preventDefault();
    if (inFlight.current || !loaded || restricted) return;
    inFlight.current = true; setBusy(true); setSaved(false); setError("");
    try {
      const result = await api<Settings>("/settings/assignment", { ...mutationOptions(csrf, { automatic_weight_adjustment: enabled, announce_table_changes: announceChanges }), method: "PUT" });
      setEnabled(result.automatic_weight_adjustment); setAnnounceChanges(result.announce_table_changes); setSaved(true);
    } catch (failure) { if (!onAccessError(failure)) setError(errorMessage(failure)); }
    finally { inFlight.current = false; setBusy(false); }
  }
  return <section className="assignment-settings" aria-labelledby="assignment-settings-heading">
    <h3 id="assignment-settings-heading">Assignments</h3>
    {!loaded && !error && <p><LoadingIndicator label="Loading assignment settings…" /></p>}
    {error && <p role="alert" className="error">{error}{!loaded && <button type="button" onClick={() => setAttempt((n) => n + 1)}>Retry</button>}</p>}
    {loaded && <form aria-label="Assignment settings" onSubmit={(event) => void save(event)}>
      <div><FormControlLabel label="Automatically Adjust Player Weights" control={<Checkbox checked={enabled} disabled={busy || restricted}
        onChange={(event) => { setEnabled(event.target.checked); setSaved(false); }} />} /></div>
      <div><FormControlLabel label="Announce Table Changes on Discord" control={<Checkbox checked={announceChanges} disabled={busy || restricted}
        onChange={(event) => { setAnnounceChanges(event.target.checked); setSaved(false); }} />} /></div>
      {saved && <p role="status">Assignment settings saved.</p>}
      <div className="form-actions"><span title={restricted ? "Only users with admin privileges can save" : undefined}><button type="submit" className="primary" disabled={busy || restricted}>{busy ? "Saving…" : "Save"}</button></span></div>
    </form>}
  </section>;
}
