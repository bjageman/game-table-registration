import { useRef, useState } from "react";
import { api, errorMessage, mutationOptions, type EventRecord } from "../../../lib/api";

export default function ReviewAssignments({ event, csrf, readOnly, onUpdated, onAccessError }: {
  event: EventRecord;
  csrf: string;
  readOnly: boolean;
  onUpdated: (event: EventRecord) => void;
  onAccessError: (error: unknown) => boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inFlight = useRef(false);
  async function approve() {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true); setError("");
    try {
      const updated = await api<EventRecord>(`/events/${encodeURIComponent(event.id)}/assignments/approve`, mutationOptions(csrf));
      onUpdated(updated);
    } catch (failure) {
      if (!onAccessError(failure)) setError(errorMessage(failure));
    } finally { setBusy(false); inFlight.current = false; }
  }
  return <>
    {error && <p role="alert" className="error">{error}</p>}
    {!readOnly && <button id={`event-approve-assignments-${event.id}`} type="button" className="primary" disabled={busy}
      onClick={() => void approve()}>{busy ? "Sending…" : "Send to Discord"}</button>}
  </>;
}
