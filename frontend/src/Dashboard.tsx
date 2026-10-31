import { useEffect, useRef, useState } from "react";
import {
  api,
  errorMessage,
  type EventRecord,
  type ModeratorSession,
} from "./api";
import EventList from "./EventList";
import EventForm from "./EventForm";

export interface DashboardProps {
  session: ModeratorSession;
  onAccessError: (error: unknown) => boolean;
}

export default function Dashboard({ session, onAccessError }: DashboardProps) {
  const [events, setEvents] = useState<EventRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [creating, setCreating] = useState(false);
  const [notice, setNotice] = useState("");
  const noticeElement = useRef<HTMLParagraphElement>(null);
  const createButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (notice) noticeElement.current?.focus();
  }, [notice]);

  function created(event: EventRecord) {
    setEvents((rows) =>
      [...rows, event].sort((a, b) => a.starts_at - b.starts_at),
    );
    setCreating(false);
    setNotice(
      `Draft saved: ${event.title}. Nothing has been posted to Discord.`,
    );
  }

  function updated(event: EventRecord) {
    setEvents((rows) => rows.map((row) => (row.id === event.id ? event : row)));
    setNotice(`Poll published: ${event.title}.`);
  }

  function uncertain(event: EventRecord, message: string) {
    setEvents((rows) =>
      rows.map((row) =>
        row.id === event.id ? { ...row, status: "unconfirmed" } : row,
      ),
    );
    setNotice(
      `${message} Publication could not be confirmed for ${event.title}. Check Discord and refresh the event list before taking further action.`,
    );
  }

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
    setNotice("");
    setAttempt((value) => value + 1);
  }

  return (
    <section aria-labelledby="events-heading">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Your community</p>
          <h2 id="events-heading">Game events</h2>
        </div>
        <div className="form-actions">
          <button
            ref={createButton}
            className="primary"
            onClick={() => {
              setCreating(true);
              setNotice("");
            }}
            disabled={creating || loading || Boolean(error)}
          >
            Create event
          </button>
          <button onClick={refresh} disabled={loading || creating}>
            {loading ? "Refreshing…" : "Refresh events"}
          </button>
        </div>
      </div>
      {notice && (
        <p role="status" className="notice" ref={noticeElement} tabIndex={-1}>
          {notice}
        </p>
      )}
      {creating && (
        <EventForm
          csrf={session.csrf}
          onCreated={created}
          onCancel={() => {
            setCreating(false);
            requestAnimationFrame(() => createButton.current?.focus());
          }}
          onAccessError={onAccessError}
        />
      )}
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
          <EventList
            events={events}
            csrf={session.csrf}
            onUpdated={updated}
            onUncertain={uncertain}
            onAccessError={onAccessError}
          />
        ) : (
          <div className="panel">
            <h3>No events yet</h3>
            <p>Event drafts and published signups will appear here.</p>
          </div>
        ))}
    </section>
  );
}
