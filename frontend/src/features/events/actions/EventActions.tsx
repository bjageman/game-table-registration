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
      await api(`/events/${encodeURIComponent(event.id)}${deletePoll ? "?delete_poll=true" : ""}`, {
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
          <p>{isDraft ? "This permanently deletes the unpublished draft and its tables." : "This permanently deletes this event and its saved signups."}</p>
          {event.discord_url && <label className="delete-poll-option">
            <input id={`event-delete-discord-checkbox-${event.id}`} type="checkbox" checked={deletePoll} disabled={busy}
              onChange={(event) => setDeletePoll(event.target.checked)} />
            Also delete the signup message on Discord
          </label>}
        </ConfirmationDialog>
      )}
    </>
  );
}
