import { useEffect, useRef, useState } from "react";
import {
  api,
  ApiError,
  errorMessage,
  mutationOptions,
  type EventRecord,
} from "./api";

export interface PublicationActions {
  csrf: string;
  onUpdated: (event: EventRecord) => void;
  onUncertain: (event: EventRecord, message: string) => void;
  onAccessError: (error: unknown) => boolean;
}

export default function PublishEvent({
  event,
  csrf,
  onUpdated,
  onUncertain,
  onAccessError,
}: PublicationActions & { event: EventRecord }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inFlight = useRef(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const [now, setNow] = useState(Date.now);
  const scheduled = Boolean(event.opens_at);
  const expired = scheduled
    ? (event.opens_at ?? 0) * 1000 <= now
    : event.starts_at * 1000 <= now + event.duration_hours * 3600000;

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!confirming) return;
    const modal = dialog.current;
    const returnFocus = trigger.current;
    modal?.showModal();
    cancel.current?.focus();
    return () => {
      modal?.close();
      returnFocus?.focus();
    };
  }, [confirming]);

  async function publish() {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      const result = await api<EventRecord>(
        `/events/${encodeURIComponent(event.id)}/${scheduled ? "schedule" : "publish"}`,
        mutationOptions(csrf),
      );
      setConfirming(false);
      onUpdated(result);
    } catch (failure) {
      if (onAccessError(failure)) return;
      if (
        failure instanceof ApiError &&
        (failure.status === 400 || failure.status === 422)
      ) {
        setError(errorMessage(failure));
      } else {
        setConfirming(false);
        onUncertain(event, errorMessage(failure));
      }
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  return (
    <>
      <button
        ref={trigger}
        className="primary"
        disabled={expired}
        onClick={() => {
          setError("");
          setConfirming(true);
        }}
      >
        {scheduled ? "Schedule signups" : "Publish to Discord"}
      </button>
      {expired && (
        <p className="help">
          The signup window would end after this event starts. Create a new
          draft with a later event time or shorter duration.
        </p>
      )}
      {confirming && (
        <dialog
          ref={dialog}
          aria-labelledby={`publish-title-${event.id}`}
          aria-describedby={`publish-description-${event.id}`}
          onCancel={(escape) => {
            if (inFlight.current) escape.preventDefault();
            else setConfirming(false);
          }}
        >
          <h2 id={`publish-title-${event.id}`}>
            {scheduled ? "Schedule" : "Publish"} {event.title}?
          </h2>
          <p id={`publish-description-${event.id}`}>
            {scheduled
              ? `The worker will publish the poll at ${new Date((event.opens_at ?? 0) * 1000).toLocaleString()} and close signups at ${new Date((event.signup_closes_at ?? 0) * 1000).toLocaleString()}.`
              : `This posts a signup poll to your configured Discord channel. Signups open immediately for ${event.duration_hours} hours.`}{" "}
            Table options and capacities freeze when publication begins.
          </p>
          <ul className="table-summary">
            {event.tables.map((table) => (
              <li key={table.name}>
                {table.name} · {table.capacity} seats
              </li>
            ))}
          </ul>
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          {busy && (
            <p role="status">
              Publishing… Keep this page open while the request completes.
            </p>
          )}
          <div className="form-actions">
            <button
              ref={cancel}
              onClick={() => setConfirming(false)}
              disabled={busy}
            >
              Cancel
            </button>
            <button
              className="primary"
              disabled={busy}
              onClick={() => void publish()}
            >
              {busy
                ? scheduled
                  ? "Scheduling…"
                  : "Publishing…"
                : scheduled
                  ? "Confirm schedule"
                  : "Confirm publication"}
            </button>
          </div>
        </dialog>
      )}
    </>
  );
}
