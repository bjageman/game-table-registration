import { useRef, useState } from "react";
import { Archive } from "lucide-react";
import ConfirmationDialog from "./ConfirmationDialog";
import { api, errorMessage, mutationOptions, type EventRecord } from "./api";
import useRememberedCheckbox from "./useRememberedCheckbox";

export default function ArchiveEvent({ event, csrf, onUpdated, onAccessError }: {
  event: EventRecord; csrf: string;
  onUpdated: (event: EventRecord, notice?: string) => void;
  onAccessError: (error: unknown) => boolean;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [deleteMessages, setDeleteMessages] = useRememberedCheckbox("delete-discord-messages-on-archive");
  const inFlight = useRef(false);
  async function archive() {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError("");
    try {
      const saved = await api<EventRecord>(`/events/${encodeURIComponent(event.id)}/archive${deleteMessages ? "?delete_discord_messages=true" : ""}`, mutationOptions(csrf));
      setConfirming(false);
      onUpdated(saved, `Event archived: ${event.title}.`);
    } catch (failure) { if (!onAccessError(failure)) setError(errorMessage(failure)); }
    finally { inFlight.current = false; setBusy(false); }
  }
  return <>
    <button type="button" className="event-icon-action" aria-label="Archive event" title="Archive Event"
      onClick={() => { setError(""); setConfirming(true); }}><Archive size={18} aria-hidden="true" /></button>
    {confirming && <ConfirmationDialog title={`Archive ${event.title}?`} busy={busy} error={error} status="Archiving…"
      onCancel={() => setConfirming(false)} onConfirm={() => void archive()}>
      <p>This keeps the event and its saved placements in the archive.</p>
      <label className="delete-poll-option"><input type="checkbox" checked={deleteMessages} disabled={busy}
        onChange={(change) => setDeleteMessages(change.target.checked)} /> Also delete the signup and assignment messages on Discord</label>
    </ConfirmationDialog>}
  </>;
}
