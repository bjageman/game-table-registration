import { useEffect, useRef, useState, type FormEvent } from "react";
import Checkbox from "@mui/material/Checkbox";
import FormControlLabel from "@mui/material/FormControlLabel";
import { api, errorMessage, mutationOptions } from "./api";

interface Settings { automatic_weight_adjustment: boolean; }

export default function AssignmentSettings({ csrf, onAccessError }: {
  csrf: string; onAccessError: (error: unknown) => boolean;
}) {
  const [enabled, setEnabled] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const inFlight = useRef(false);
  useEffect(() => {
    const controller = new AbortController();
    api<Settings>("/settings/assignment", { signal: controller.signal }).then((value) => {
      if (!controller.signal.aborted) { setEnabled(value.automatic_weight_adjustment); setLoaded(true); setError(""); }
    }).catch((failure) => { if (!controller.signal.aborted && !onAccessError(failure)) setError(errorMessage(failure)); });
    return () => controller.abort();
  }, [attempt, onAccessError]);
  async function save(event: FormEvent) {
    event.preventDefault();
    if (inFlight.current || !loaded) return;
    inFlight.current = true; setBusy(true); setSaved(false); setError("");
    try {
      const result = await api<Settings>("/settings/assignment", { ...mutationOptions(csrf, { automatic_weight_adjustment: enabled }), method: "PUT" });
      setEnabled(result.automatic_weight_adjustment); setSaved(true);
    } catch (failure) { if (!onAccessError(failure)) setError(errorMessage(failure)); }
    finally { inFlight.current = false; setBusy(false); }
  }
  return <section className="assignment-settings" aria-labelledby="assignment-settings-heading">
    <h3 id="assignment-settings-heading">Assignments</h3>
    {!loaded && !error && <p role="status">Loading assignment settings…</p>}
    {error && <p role="alert" className="error">{error}{!loaded && <button type="button" onClick={() => setAttempt((n) => n + 1)}>Retry</button>}</p>}
    {loaded && <form aria-label="Assignment settings" onSubmit={(event) => void save(event)}>
      <FormControlLabel label="Automatically Adjust Player Weights" control={<Checkbox checked={enabled} disabled={busy}
        onChange={(event) => { setEnabled(event.target.checked); setSaved(false); }} />} />
      {saved && <p role="status">Assignment settings saved.</p>}
      <div className="form-actions"><button type="submit" className="primary" disabled={busy}>{busy ? "Saving…" : "Save"}</button></div>
    </form>}
  </section>;
}
