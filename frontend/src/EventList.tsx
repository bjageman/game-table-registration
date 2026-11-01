import { isBackdropClick } from "./dialogBackdrop";
import { useEffect, useRef, useState } from "react";
import { Eye, RefreshCw, X } from "lucide-react";
import ArchiveEvent from "./ArchiveEvent";
import EventTables from "./EventTables";
import DiscordLink from "./DiscordLink";
import PopulateTestUsers from "./PopulateTestUsers";
import AssignmentAnnouncement from "./AssignmentAnnouncement";
import CloseSignups from "./CloseSignups";
import EventActions from "./EventActions";
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
  canPopulateTestUsers = false,
  onEdit,
  onDeleted,
  ...actions
}: {
  events: EventRecord[];
  canPopulateTestUsers?: boolean;
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
              <span className="event-list-top">
                <span className="event-list-title">{event.title}</span>
                <span className={`badge ${event.status === "draft" ? "draft" : ""}`}>
                  {event.archived_at ? "Archived" : event.status.replaceAll("_", " ")}{event.is_test ? " · test" : ""}
                </span>
                <span className="event-table-count">{event.tables.length} {event.tables.length === 1 ? "table" : "tables"}</span>
              </span>
              <span className="event-list-dates help">
                <span>Event: <ListTime timestamp={event.starts_at} /></span>
                <span>Signups: {event.closes_at !== null ? <>
                  <ListTime timestamp={event.published_at ?? event.closes_at - event.duration_hours * 3600} />
                  {" – "}<ListTime timestamp={event.closes_at} />
                </> : "Not scheduled"}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
      {selected && <EventDetails
        event={selected}
        canPopulateTestUsers={canPopulateTestUsers}
        onClose={() => setSelectedId(null)}
        onEdit={onEdit}
        onDeleted={onDeleted}
        {...actions}
      />}
    </>
  );
}

function EventDetails({ event, canPopulateTestUsers, onClose, onEdit, onDeleted, ...actions }: {
  event: EventRecord;
  canPopulateTestUsers: boolean;
  onClose: () => void;
  onEdit: (event: EventRecord) => void;
  onDeleted: (event: EventRecord) => void;
} & PublicationActions) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
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
    <dialog onClick={(event) => { if (isBackdropClick(event)) onClose(); }} ref={dialog} className="event-modal" aria-labelledby={`event-${event.id}`}
      onCancel={(event) => { event.preventDefault(); onClose(); }}>
      <div className="event-modal-header">
        <h2 id={`event-${event.id}`}>{event.title}</h2>
        <span className={`badge ${event.status === "draft" ? "draft" : ""}`}>
          {event.archived_at ? "Archived" : event.status.replaceAll("_", " ")}{event.is_test ? " · test" : ""}
        </span>
        <div className="event-header-actions">
          {event.status !== "draft" && (
          <button type="button" className="event-icon-action"
            aria-label={refreshing ? "Refreshing signups" : "Refresh signups"}
            title={refreshing ? "Refreshing Signups" : "Refresh Signups"}
            disabled={refreshing || !event.discord_url}
            onClick={() => setRefreshToken((value) => value + 1)}>
            <RefreshCw size={18} aria-hidden="true" />
          </button>
          )}
          {event.discord_url && (
            <DiscordLink className="button event-icon-action" url={event.discord_url} label={`View Discord poll for ${event.title}`}>
              <Eye size={18} aria-hidden="true" />
            </DiscordLink>
          )}
          {event.status === "assigned" && !event.archived_at && <ArchiveEvent event={event} csrf={actions.csrf} onUpdated={actions.onUpdated} onAccessError={actions.onAccessError} />}
          {event.status === "draft" && <PublishEvent event={event} {...actions} />}
          {(event.status === "draft" || event.status === "open") && (
            <>
                <EventActions
                  event={event}
                  csrf={actions.csrf}
                  onEdit={(edited) => { onClose(); onEdit(edited); }}
                  onDeleted={onDeleted}
                  onAccessError={actions.onAccessError}
                />
            </>
          )}
        </div>
        <button type="button" onClick={onClose} aria-label="Close event" title="Close event" autoFocus>
          <X size={18} aria-hidden="true" />
        </button>
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
            {event.is_test && <p className="notice">Test event: includes {event.test_user_count} simulated signups stored in TableSignup. Announcements will be marked TEST.</p>}
            <EventTables key={`${event.id}:${event.discord_url}:${event.status}:${event.test_generation ?? ""}`} event={event} csrf={actions.csrf} refreshToken={refreshToken} onRefreshingChange={setRefreshing} onAccessError={actions.onAccessError} />
            {event.status === "closing" && <p role="status" className="notice">
              {event.close_error ?? "Signups are closing. Placements are waiting for Discord's final vote totals."}
            </p>}
            <div className="form-actions">
              {(event.status === "open" || event.status === "closing") && <CloseSignups event={event} csrf={actions.csrf} onUpdated={actions.onUpdated} onAccessError={actions.onAccessError} />}
              {canPopulateTestUsers && (event.status === "draft" || event.status === "open") && <PopulateTestUsers event={event} csrf={actions.csrf} onUpdated={actions.onUpdated} onAccessError={actions.onAccessError} />}
            </div>
            {event.status === "assigned" && <AssignmentAnnouncement event={event} csrf={actions.csrf} refreshToken={refreshToken} onAccessError={actions.onAccessError} />}
            {(event.status === "publishing" ||
              event.status === "needs_review" ||
              event.status === "unconfirmed") && (
              <p className="notice">
                Check Discord before taking further action. Publication has not
                been confirmed; this event will not be retried automatically.
              </p>
            )}
    </dialog>
  );
}

function ListTime({ timestamp }: { timestamp: number }) {
  return <time dateTime={new Date(timestamp * 1000).toISOString()}>
    {new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(timestamp * 1000))}
  </time>;
}
