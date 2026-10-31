import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import EventTables from "./EventTables";
import DraftActions from "./DraftActions";
import type { EventRecord } from "./api";
import PublishEvent, { type PublicationActions } from "./PublishEvent";

export function formatTime(timestamp: number): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "long",
  }).format(new Date(timestamp * 1000));
}

export default function EventList({
  events,
  onEdit,
  onDeleted,
  ...actions
}: {
  events: EventRecord[];
  onEdit: (event: EventRecord) => void;
  onDeleted: (event: EventRecord) => void;
} & PublicationActions) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = events.find((event) => event.id === selectedId);
  return (
    <>
      <ul className="event-list">
        {events.map((event) => (
          <li key={event.id}>
            <button
              type="button"
              className="event-list-item"
              aria-haspopup="dialog"
              onClick={() => setSelectedId(event.id)}
            >
              <span className="event-list-title">{event.title}</span>
              <span className="help">{event.tables.length} {event.tables.length === 1 ? "table" : "tables"}</span>
            </button>
          </li>
        ))}
      </ul>
      {selected && <EventDetails
        event={selected}
        onClose={() => setSelectedId(null)}
        onEdit={onEdit}
        onDeleted={onDeleted}
        {...actions}
      />}
    </>
  );
}

function EventDetails({ event, onClose, onEdit, onDeleted, ...actions }: {
  event: EventRecord;
  onClose: () => void;
  onEdit: (event: EventRecord) => void;
  onDeleted: (event: EventRecord) => void;
} & PublicationActions) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const modal = dialog.current;
    const trigger = document.activeElement;
    modal?.showModal();
    return () => {
      modal?.close();
      if (trigger instanceof HTMLElement && trigger.isConnected) trigger.focus();
    };
  }, []);
  return (
    <dialog ref={dialog} className="event-modal" aria-labelledby={`event-${event.id}`}
      onCancel={(event) => { event.preventDefault(); onClose(); }}>
      <div className="event-modal-close">
        <button type="button" onClick={onClose} aria-label="Close event" title="Close event" autoFocus>
          <X size={18} aria-hidden="true" />
        </button>
      </div>
            <div className="section-heading">
              <h2 id={`event-${event.id}`}>{event.title}</h2>
              <span
                className={`badge ${event.status === "draft" ? "draft" : ""}`}
              >
                {event.status.replaceAll("_", " ")}
              </span>
            </div>
            <dl className="event-details">
              <div>
                <dt>Event starts</dt>
                <dd>
                  <time
                    dateTime={new Date(event.starts_at * 1000).toISOString()}
                  >
                    {formatTime(event.starts_at)}
                  </time>
                </dd>
              </div>
              <div>
                <dt>Signup duration</dt>
                <dd>{event.duration_hours} hours from publication</dd>
              </div>
              {event.closes_at !== null && (
                <div>
                  <dt>Signups close</dt>
                  <dd>
                    <time
                      dateTime={new Date(event.closes_at * 1000).toISOString()}
                    >
                      {formatTime(event.closes_at)}
                    </time>
                  </dd>
                </div>
              )}
            </dl>
            <EventTables event={event} />
            {(event.status === "publishing" ||
              event.status === "needs_review" ||
              event.status === "unconfirmed") && (
              <p className="notice">
                Check Discord before taking further action. Publication has not
                been confirmed; this event will not be retried automatically.
              </p>
            )}
            {event.status === "draft" && (
              <div className="form-actions draft-actions">
                <PublishEvent event={event} {...actions} />
                <DraftActions
                  event={event}
                  csrf={actions.csrf}
                  onEdit={(edited) => { onClose(); onEdit(edited); }}
                  onDeleted={onDeleted}
                  onAccessError={actions.onAccessError}
                />
              </div>
            )}
            {event.discord_url && (
              <a
                className="button"
                href={event.discord_url}
                target="_blank"
                rel="noreferrer"
              >
                View Discord poll
                <span className="sr-only">
                  {" "}
                  for {event.title} (opens in a new tab)
                </span>
              </a>
            )}
    </dialog>
  );
}
