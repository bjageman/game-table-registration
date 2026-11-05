import { useEffect, useRef, useState, type FormEvent } from "react";
import Checkbox from "@mui/material/Checkbox";
import FormControlLabel from "@mui/material/FormControlLabel";
import { api, errorMessage, mutationOptions } from "../../lib/api";
import LoadingIndicator from "../../components/LoadingIndicator";

interface Settings { automatic_weight_adjustment: boolean; announce_table_changes: boolean; post_discord_updates_to_thread: boolean; }

export default function AssignmentSettings({ csrf, restricted = false, onAccessError }: {
  csrf: string; restricted?: boolean; onAccessError: (error: unknown) => boolean;
}) {
  const [enabled, setEnabled] = useState(true);
  const [announceChanges, setAnnounceChanges] = useState(false);
  const [threadUpdates, setThreadUpdates] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const inFlight = useRef(false);
  useEffect(() => {
    const controller = new AbortController();
    api<Settings>("/settings/assignment", { signal: controller.signal }).then((value) => {
      if (!controller.signal.aborted) { setEnabled(value.automatic_weight_adjustment); setAnnounceChanges(value.announce_table_changes); setThreadUpdates(value.post_discord_updates_to_thread ?? false); setLoaded(true); setError(""); }
    }).catch((failure) => { if (!controller.signal.aborted && !onAccessError(failure)) setError(errorMessage(failure)); });
    return () => controller.abort();
  }, [attempt, onAccessError]);
  async function save(event: FormEvent) {
    event.preventDefault();
    if (inFlight.current || !loaded || restricted) return;
    inFlight.current = true; setBusy(true); setSaved(false); setError("");
    try {
      const result = await api<Settings>("/settings/assignment", { ...mutationOptions(csrf, { automatic_weight_adjustment: enabled, announce_table_changes: announceChanges, post_discord_updates_to_thread: threadUpdates }), method: "PUT" });
      setEnabled(result.automatic_weight_adjustment); setAnnounceChanges(result.announce_table_changes); setThreadUpdates(result.post_discord_updates_to_thread ?? false); setSaved(true);
    } catch (failure) { if (!onAccessError(failure)) setError(errorMessage(failure)); }
    finally { inFlight.current = false; setBusy(false); }
  }
  return <section className="assignment-settings" aria-label="Assignment settings">
    {!loaded && !error && <p><LoadingIndicator label="Loading assignment settings…" /></p>}
    {error && <p role="alert" className="error">{error}{!loaded && <button type="button" onClick={() => setAttempt((n) => n + 1)}>Retry</button>}</p>}
    {loaded && <form aria-label="Assignment settings" onSubmit={(event) => void save(event)}>
      <div><FormControlLabel label="Automatically Adjust Player Weights" control={<Checkbox checked={enabled} disabled={busy || restricted}
        onChange={(event) => { setEnabled(event.target.checked); setSaved(false); }} />} /></div>
      <div><FormControlLabel label="Announce Table Changes on Discord" control={<Checkbox checked={announceChanges} disabled={busy || restricted}
        onChange={(event) => { setAnnounceChanges(event.target.checked); setSaved(false); }} />} /></div>
      <div><FormControlLabel label="Post Discord updates to a new thread" control={<Checkbox checked={threadUpdates} disabled={busy || restricted}
        onChange={(event) => { setThreadUpdates(event.target.checked); setSaved(false); }} />} /></div>
      {threadUpdates && <p className="help">The bot needs Create Public Threads and Send Messages in Threads permissions in the signup channel.</p>}
      {saved && <p role="status">Assignment settings saved.</p>}
      <div className="form-actions"><span title={restricted ? "Only users with admin privileges can save" : undefined}><button type="submit" className="primary" disabled={busy || restricted}>{busy ? "Saving…" : "Save"}</button></span></div>
    </form>}
  </section>;
}
