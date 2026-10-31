import { useEffect, useId, useRef, useState } from "react";
import { Pencil, Trash2 } from "lucide-react";
import { api, errorMessage, mutationOptions, type EventRecord } from "./api";

export default function DraftActions({
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
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inFlight = useRef(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const heading = useId();
  useEffect(() => {
    if (confirming) dialog.current?.showModal();
  }, [confirming]);
  function close() {
    dialog.current?.close();
    setConfirming(false);
    trigger.current?.focus();
  }
  async function remove() {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      await api(`/events/${event.id}`, {
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
      <button type="button" className="event-icon-action" aria-label="Edit draft" title="Edit Draft" onClick={() => onEdit(event)}>
        <Pencil size={18} aria-hidden="true" />
      </button>
      <button
        type="button"
        ref={trigger}
        className="event-icon-action"
        aria-label="Delete draft"
        title="Delete Draft"
        onClick={() => {
          setError("");
          setConfirming(true);
        }}
      >
        <Trash2 size={18} aria-hidden="true" />
      </button>
      {confirming && (
        <dialog
          ref={dialog}
          aria-labelledby={heading}
          onCancel={(e) => {
            e.preventDefault();
            if (!busy) close();
          }}
        >
          <h2 id={heading}>Delete {event.title}?</h2>
          <p>This permanently deletes the unpublished draft and its tables.</p>
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          <div className="form-actions">
            <button type="button" autoFocus disabled={busy} onClick={close}>
              Cancel
            </button>
            <button type="button" disabled={busy} onClick={() => void remove()}>
              {busy ? "Deleting…" : "Confirm deletion"}
            </button>
          </div>
        </dialog>
      )}
    </>
  );
}
