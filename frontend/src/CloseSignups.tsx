import { useEffect, useRef, useState } from "react";
import ConfirmationDialog from "./ConfirmationDialog";
import { api, errorMessage, mutationOptions, type EventRecord } from "./api";

export default function CloseSignups({ event, csrf, onUpdated, onAccessError }: {
  event: EventRecord;
  csrf: string;
  onUpdated: (event: EventRecord) => void;
  onAccessError: (error: unknown) => boolean;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inFlight = useRef(false);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  async function close() {
    if (inFlight.current) return;
    inFlight.current = true;
    const operation = new AbortController();
    controller.current = operation;
    setBusy(true); setError("");
    try {
      for (let attempt = 0; attempt < 15; attempt++) {
        if (operation.signal.aborted) return;
        const result = await api<EventRecord>(`/events/${encodeURIComponent(event.id)}/close`, {
          ...mutationOptions(csrf), signal: operation.signal,
        });
        if (result.status === "assigned") {
          setConfirming(false);
          onUpdated(result);
          return;
        }
        if (result.status !== "closing") throw new Error("Unexpected closing status. Refresh the event before trying again.");
        onUpdated(result);
        // A 202/closing response explicitly asks us to continue finalization.
        await new Promise((resolve) => setTimeout(resolve, 2000));
      }
      if (!operation.signal.aborted) setError("Discord is still finalizing votes. Confirm again to finish; placements will only be drawn once.");
    } catch (failure) {
      if (!operation.signal.aborted && !onAccessError(failure)) setError(errorMessage(failure));
    } finally {
      inFlight.current = false;
      if (!operation.signal.aborted) setBusy(false);
    }
  }
  return <>
    <button type="button" className="primary" onClick={() => { setError(""); setConfirming(true); }}>Close Signups</button>
    {confirming && <ConfirmationDialog title={`Close signups for ${event.title}?`}
      busy={busy} error={error} status="Closing the Discord poll and determining placement…"
      onCancel={() => setConfirming(false)} onConfirm={() => void close()}>
      <p>This closes the Discord poll and assigns players to tables. The saved placements cannot be redrawn.</p>
    </ConfirmationDialog>}
  </>;
}
