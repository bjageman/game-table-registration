import { useEffect, useRef, useState } from "react";
import TextField from "@mui/material/TextField";
import { api, errorMessage, mutationOptions, type EventRecord } from "./api";

export default function RecoverEvent({
  event,
  csrf,
  onUpdated,
  onAccessError,
}: {
  event: EventRecord;
  csrf: string;
  onUpdated: (event: EventRecord) => void;
  onAccessError: (error: unknown) => boolean;
}) {
  const [open, setOpen] = useState(false);
  const [messageId, setMessageId] = useState(event.message_id ?? "");
  const [reason, setReason] = useState("");
  const [acceptLate, setAcceptLate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const inFlight = useRef(false);
  useEffect(() => {
    if (open) dialog.current?.showModal();
  }, [open]);
  function close() {
    dialog.current?.close();
    setOpen(false);
    trigger.current?.focus();
  }
  async function recover() {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      const updated = await api<EventRecord>(
        `/events/${event.id}/recover`,
        mutationOptions(csrf, {
          message_id: messageId || undefined,
          reason,
          accept_late_votes: acceptLate,
        }),
      );
      close();
      onUpdated(updated);
    } catch (failure) {
      if (!onAccessError(failure)) setError(errorMessage(failure));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }
  return (
    <>
      <button type="button" ref={trigger} onClick={() => setOpen(true)}>
        Review existing poll
      </button>
      {open && (
        <dialog
          ref={dialog}
          aria-labelledby={`recovery-${event.id}`}
          onCancel={(e) => {
            e.preventDefault();
            if (!busy) close();
          }}
        >
          <h2 id={`recovery-${event.id}`}>Recover {event.title}</h2>
          <p>
            Check Discord and link the existing poll. This does not create
            another message. A missed custom deadline may include later votes.
          </p>
          <fieldset disabled={busy} className="schedule-fields">
            <div className="form-grid">
              <TextField
                label="Discord poll message ID"
                value={messageId}
                onChange={(e) => setMessageId(e.target.value)}
                fullWidth
                slotProps={{ inputLabel: { shrink: true } }}
              />
              <TextField
                label="Recovery reason"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                fullWidth
                slotProps={{
                  inputLabel: { shrink: true },
                  htmlInput: { minLength: 10, maxLength: 300 },
                }}
              />
            </div>
            <label className="schedule-toggle">
              <input
                type="checkbox"
                checked={acceptLate}
                onChange={(e) => setAcceptLate(e.target.checked)}
              />{" "}
              Accept later votes if the custom deadline was missed
            </label>
          </fieldset>
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          <div className="form-actions">
            <button type="button" autoFocus disabled={busy} onClick={close}>
              Cancel
            </button>
            <button
              type="button"
              disabled={busy || reason.trim().length < 10}
              onClick={() => void recover()}
            >
              {busy ? "Checking…" : "Confirm recovery"}
            </button>
          </div>
        </dialog>
      )}
    </>
  );
}
