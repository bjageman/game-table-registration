import ConfirmationDialog from "../../../components/ConfirmationDialog";
import { useRef, useState } from "react";
import { Pencil, Trash2 } from "lucide-react";
import { api, errorMessage, mutationOptions, type EventRecord } from "../../../lib/api";
import useRememberedCheckbox from "../../../hooks/useRememberedCheckbox";

export default function EventActions({
  event,
  csrf,
  onEdit,
  onDeleted,
  onAccessError,
}: {
  event: EventRecord;
  csrf: string;
  onEdit: (event: EventRecord) => void;
  onDeleted: (event: EventRecord) => void;
  onAccessError: (error: unknown) => boolean;
}) {
  const [deletePoll, setDeletePoll] = useRememberedCheckbox("delete-discord-signup-on-event-delete");
  const [deleteDiscordEvent, setDeleteDiscordEvent] = useRememberedCheckbox("delete-discord-event-on-delete");
  const isDraft = event.status === "draft";
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inFlight = useRef(false);
  async function remove() {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      const query = new URLSearchParams();
      if (deletePoll) query.set("delete_poll", "true");
      if (event.has_discord_event && deleteDiscordEvent) query.set("delete_discord_event", "true");
      await api(`/events/${encodeURIComponent(event.id)}${query.size ? `?${query}` : ""}`, {
        ...mutationOptions(csrf),
        method: "DELETE",
      });
      onDeleted(event);
    } catch (failure) {
      if (!onAccessError(failure)) setError(errorMessage(failure));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }
  return (
    <>
      {isDraft && <button id={`event-edit-${event.id}`} type="button" className="event-icon-action" aria-label="Edit draft" title="Edit Draft" onClick={() => onEdit(event)}>
        <Pencil size={18} aria-hidden="true" />
      </button>}
      <button
        id={`event-delete-${event.id}`}
        type="button"
        className="event-icon-action"
        aria-label={isDraft ? "Delete draft" : "Delete signup"}
        title={isDraft ? "Delete Draft" : "Delete Sign-up"}
        onClick={() => {
          setError("");
          setConfirming(true);
        }}
      >
        <Trash2 size={18} aria-hidden="true" />
      </button>
      {confirming && (
        <ConfirmationDialog id={`event-delete-dialog-${event.id}`}
          title={`Delete ${event.title}?`}
          busy={busy}
          error={error}
          status="Deleting…"
          onCancel={() => setConfirming(false)}
          onConfirm={() => void remove()}
        >
          {event.discord_url && <label className="delete-poll-option">
            <input id={`event-delete-discord-checkbox-${event.id}`} type="checkbox" checked={deletePoll} disabled={busy}
              onChange={(event) => setDeletePoll(event.target.checked)} />
            Also delete the signup message on Discord
          </label>}
          {event.has_discord_event && <label className="delete-poll-option">
            <input type="checkbox" checked={deleteDiscordEvent} disabled={busy}
              onChange={(change) => setDeleteDiscordEvent(change.target.checked)} />
            Delete Discord event
          </label>}
        </ConfirmationDialog>
      )}
    </>
  );
}
