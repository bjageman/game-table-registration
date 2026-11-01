import { useRef, useState } from "react";
import { Archive } from "lucide-react";
import ConfirmationDialog from "./ConfirmationDialog";
import { api, errorMessage, mutationOptions, type EventRecord } from "./api";

export default function ArchiveEvent({ event, csrf, onUpdated, onAccessError }: {
  event: EventRecord; csrf: string;
  onUpdated: (event: EventRecord, notice?: string) => void;
  onAccessError: (error: unknown) => boolean;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inFlight = useRef(false);
  async function archive() {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError("");
    try {
      const saved = await api<EventRecord>(`/events/${encodeURIComponent(event.id)}/archive`, mutationOptions(csrf));
      setConfirming(false);
      onUpdated(saved, `Event archived: ${event.title}.`);
    } catch (failure) { if (!onAccessError(failure)) setError(errorMessage(failure)); }
    finally { inFlight.current = false; setBusy(false); }
  }
  return <>
    <button type="button" className="event-icon-action" aria-label="Archive event" title="Archive Event"
      onClick={() => { setError(""); setConfirming(true); }}><Archive size={18} aria-hidden="true" /></button>
    {confirming && <ConfirmationDialog title={`Archive ${event.title}?`} busy={busy} error={error} status="Archiving…"
      onCancel={() => setConfirming(false)} onConfirm={() => void archive()}>{null}</ConfirmationDialog>}
  </>;
}
