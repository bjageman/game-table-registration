import { useEffect, useRef, useState } from "react";
import ConfirmationDialog from "../../../components/ConfirmationDialog";
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
  const [confirming, setConfirming] = useState(false);
  const [deleteSignup, setDeleteSignup] = useState(false);
  const inFlight = useRef(false);
  useEffect(() => {
    if (!event.assignment_publication_pending) return;
    const controller = new AbortController();
    const timer = setInterval(() => {
      api<EventRecord[]>("/events", { signal: controller.signal }).then((events) => {
        if (controller.signal.aborted) return;
        const current = events.find((row) => row.id === event.id);
        if (current?.status === "assigned") onUpdated(current);
        else if (current?.assignment_publication_error) setError(`Assignments have not been posted to Discord. ${current.assignment_publication_error}`);
      }).catch((failure) => { if (!controller.signal.aborted && !onAccessError(failure)) setError(errorMessage(failure)); });
    }, 3000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [event.id, event.assignment_publication_pending, onUpdated, onAccessError]);
  async function approve() {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true); setError("");
    try {
      const suffix = deleteSignup ? "?delete_signup_message=true" : "";
      const updated = await api<EventRecord>(`/events/${encodeURIComponent(event.id)}/assignments/approve${suffix}`, mutationOptions(csrf));
      onUpdated(updated);
      if (updated.status !== "assigned") {
        setError(`Assignments have not been posted to Discord. ${updated.assignment_publication_error || "Delivery is still pending. You can retry shortly."}`);
      } else setConfirming(false);
    } catch (failure) {
      if (!onAccessError(failure)) setError(errorMessage(failure));
    } finally { setBusy(false); inFlight.current = false; }
  }
  return <>
    {event.assignment_publication_error && !error && <p role="alert" className="error">Assignments have not been posted to Discord. {event.assignment_publication_error}</p>}
    {error && !confirming && <p role="alert" className="error">{error}</p>}
    {!readOnly && <button id={`event-approve-assignments-${event.id}`} type="button" className="primary" disabled={busy}
      onClick={() => { setError(""); setConfirming(true); }}>Send to Discord</button>}
    {confirming && <ConfirmationDialog id={`event-approve-assignments-dialog-${event.id}`} title="Send assignments to Discord?"
      busy={busy} error={error} onCancel={() => setConfirming(false)} onConfirm={() => void approve()}>
      <p>Are you sure you want to send these assignments?</p>
      {event.discord_url && <label className="delete-poll-option"><input type="checkbox" checked={deleteSignup} disabled={busy}
        onChange={(change) => setDeleteSignup(change.target.checked)} /> Also delete the signup message on Discord</label>}
    </ConfirmationDialog>}
  </>;
}
