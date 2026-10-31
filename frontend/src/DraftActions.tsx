import { useEffect, useId, useRef, useState } from "react";
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
  const cancelling = event.status !== "draft" || Boolean(event.schedule_id);
  const editable = ["draft", "scheduled", "paused"].includes(event.status);
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
      await api(`/events/${event.id}${cancelling ? "/cancel" : ""}`, {
        ...mutationOptions(csrf),
        method: cancelling ? "POST" : "DELETE",
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
      {editable && (
        <button type="button" onClick={() => onEdit(event)}>
          {event.status === "draft" ? "Edit draft" : "Edit this occurrence"}
        </button>
      )}
      <button
        type="button"
        ref={trigger}
        onClick={() => {
          setError("");
          setConfirming(true);
        }}
      >
        {cancelling ? "Cancel this occurrence" : "Delete draft"}
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
          <h2 id={heading}>
            {cancelling ? "Cancel" : "Delete"} {event.title}?
          </h2>
          <p>
            {cancelling
              ? "This skips this occurrence. Any open signup poll will be ended and its votes will not be assigned."
              : "This permanently deletes the unpublished draft and its tables."}
          </p>
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
              {busy
                ? "Working…"
                : cancelling
                  ? "Confirm cancellation"
                  : "Confirm deletion"}
            </button>
          </div>
        </dialog>
      )}
    </>
  );
}
