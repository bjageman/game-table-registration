import ConfirmationDialog from "./ConfirmationDialog";
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
        className="primary"
        disabled={expired}
        onClick={() => {
          setError("");
          setConfirming(true);
        }}
      >
        Publish to Discord
      </button>
      {expired && (
        <p className="help">
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
          <p id={`publish-description-${event.id}`}>
            This posts a signup poll to your configured Discord channel. Signups
            open immediately for {event.duration_hours} hours. Table options and
            capacities cannot be edited after publication.
          </p>
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
