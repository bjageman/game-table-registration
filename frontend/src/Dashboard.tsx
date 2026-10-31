import { useEffect, useState } from "react";
import {
  api,
  errorMessage,
  type EventRecord,
  type ModeratorSession,
} from "./api";
import EventList from "./EventList";

export interface DashboardProps {
  session: ModeratorSession;
  onAccessError: (error: unknown) => boolean;
}

export default function Dashboard({ onAccessError }: DashboardProps) {
  const [events, setEvents] = useState<EventRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    api<EventRecord[]>("/events", { signal: controller.signal })
      .then((value) => {
        if (!controller.signal.aborted) setEvents(value);
      })
      .catch((failure) => {
        if (!controller.signal.aborted && !onAccessError(failure))
          setError(errorMessage(failure));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [attempt, onAccessError]);

  function refresh() {
    setLoading(true);
    setError("");
    setAttempt((value) => value + 1);
  }

  return (
    <section aria-labelledby="events-heading">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Your community</p>
          <h2 id="events-heading">Game events</h2>
        </div>
        <button onClick={refresh} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh events"}
        </button>
      </div>
      {loading && <p role="status">Loading events…</p>}
      {error && (
        <div className="panel">
          <p role="alert" className="error">
            {error}
          </p>
          <button onClick={refresh}>Try again</button>
        </div>
      )}
      {!loading &&
        !error &&
        (events.length ? (
          <EventList events={events} />
        ) : (
          <div className="panel">
            <h3>No events yet</h3>
            <p>Event drafts and published signups will appear here.</p>
          </div>
        ))}
    </section>
  );
}
