import ConfirmationDialog from "./ConfirmationDialog";
import { useRef, useState } from "react";
import { Pencil, Trash2 } from "lucide-react";
import { api, errorMessage, mutationOptions, type EventRecord } from "./api";

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
  const [deletePoll, setDeletePoll] = useState(false);
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
      {isDraft && <button type="button" className="event-icon-action" aria-label="Edit draft" title="Edit Draft" onClick={() => onEdit(event)}>
        <Pencil size={18} aria-hidden="true" />
      </button>}
      <button
        type="button"
        className="event-icon-action"
        aria-label={isDraft ? "Delete draft" : "Delete signup"}
        title={isDraft ? "Delete Draft" : "Delete Sign-up"}
        onClick={() => {
          setError("");
          setDeletePoll(false);
          setConfirming(true);
        }}
      >
        <Trash2 size={18} aria-hidden="true" />
      </button>
      {confirming && (
        <ConfirmationDialog
          title={`Delete ${event.title}?`}
          busy={busy}
          error={error}
          status="Deleting…"
          onCancel={() => setConfirming(false)}
          onConfirm={() => void remove()}
        >
          <p>{isDraft ? "This permanently deletes the unpublished draft and its tables." : "This permanently removes the signup from TableSignup."}</p>
          {event.discord_url && <label className="delete-poll-option">
            <input type="checkbox" checked={deletePoll} disabled={busy}
              onChange={(event) => setDeletePoll(event.target.checked)} />
            Also delete the poll on Discord
          </label>}
        </ConfirmationDialog>
      )}
    </>
  );
}
