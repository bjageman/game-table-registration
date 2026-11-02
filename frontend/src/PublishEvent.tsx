import { Send } from "lucide-react";
import ConfirmationDialog from "./ConfirmationDialog";
import { useEffect, useId, useRef, useState } from "react";
import {
  api,
  ApiError,
  errorMessage,
  mutationOptions,
  type EventRecord,
} from "./api";

export interface PublicationActions {
  csrf: string;
  onUpdated: (event: EventRecord, message?: string) => void;
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
  const expirationHint = useId();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inFlight = useRef(false);
  const [now, setNow] = useState(Date.now);
  const expired =
    event.starts_at * 1000 <= now + event.duration_hours * 3600000;

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(timer);
  }, []);

  async function publish() {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      const result = await api<EventRecord>(
        `/events/${encodeURIComponent(event.id)}/publish`,
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
        className="primary event-icon-action"
        type="button"
        aria-label="Publish to Discord"
        aria-describedby={expired ? expirationHint : undefined}
        title={expired ? "Choose a later event time or shorter signup duration before publishing" : "Publish to Discord"}
        disabled={expired}
        onClick={() => {
          setError("");
          setConfirming(true);
        }}
      >
        <Send size={18} aria-hidden="true" />
      </button>
      {expired && (
        <p className="sr-only" id={expirationHint}>
          The signup window would end after this event starts. Create a new
          draft with a later event time or shorter duration.
        </p>
      )}
      {confirming && (
        <ConfirmationDialog
          title={`Publish ${event.title}?`}
          busy={busy}
          error={error}
          status="Publishing… Keep this page open while the request completes."
          onCancel={() => setConfirming(false)}
          onConfirm={() => void publish()}
        >
          <p>Players choose their specific tables directly in Discord. Signing up enters the lottery for those tables.</p>
          <ul className="table-summary">
            {event.tables.map((table) => (
              <li key={table.name}>
                {table.name} · {table.capacity} seats
              </li>
            ))}
          </ul>
        </ConfirmationDialog>
      )}
    </>
  );
}
