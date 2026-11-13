import { useState } from "react";
import ConfirmationDialog from "../../../components/ConfirmationDialog";
import { api, errorMessage, mutationOptions, type EventRecord } from "../../../lib/api";

export default function DeleteSignupMessage({ event, csrf, onUpdated, onAccessError }: {
  event: EventRecord; csrf: string;
  onUpdated: (event: EventRecord) => void;
  onAccessError: (error: unknown) => boolean;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function remove() {
    if (busy) return;
    setBusy(true); setError("");
    try {
      const saved = await api<EventRecord>(`/events/${encodeURIComponent(event.id)}/signup-message/delete`, mutationOptions(csrf));
      setConfirming(false); onUpdated(saved);
    } catch (failure) { if (!onAccessError(failure)) setError(errorMessage(failure)); }
    finally { setBusy(false); }
  }
  return <>
    <button id={`event-delete-signup-message-${event.id}`} type="button" onClick={() => setConfirming(true)}>Delete Discord signup message</button>
    {confirming && <ConfirmationDialog id={`event-delete-signup-message-dialog-${event.id}`} title={`Delete Discord signup for ${event.title}?`} busy={busy} error={error}
      status="Deleting…" onCancel={() => setConfirming(false)} onConfirm={() => void remove()}>
      {null}
    </ConfirmationDialog>}
  </>;
}
