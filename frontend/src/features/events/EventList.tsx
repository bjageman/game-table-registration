import EventDateLine from "../../components/EventDateLine";
import { useTimezone, formatTimestamp } from "../../lib/timezone";
import ModalHeader from "../../components/ModalHeader";
import { isBackdropClick } from "../../lib/dialogBackdrop";
import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import ArchiveEvent from "./actions/ArchiveEvent";
import ShareEvent from "./sharing/ShareEvent";
import DeleteDiscordMessages from "./actions/DeleteDiscordMessages";
import DeleteSignupMessage from "./actions/DeleteSignupMessage";
import EventTables from "./assignments/EventTables";
import DiscordLink from "../../components/DiscordLink";
import { DiscordIcon } from "../../components/DiscordIcon";
import PopulateTestUsers from "./actions/PopulateTestUsers";
import AssignmentAnnouncement from "./assignments/AssignmentAnnouncement";
import SignupDownload from "./exports/SignupDownload";
import CloseSignups from "./actions/CloseSignups";
import EventActions from "./actions/EventActions";
import type { EventRecord } from "../../lib/api";
import PublishEvent, { type PublicationActions } from "./actions/PublishEvent";

export default function EventList({
  events,
  canPopulateTestUsers = false,
  readOnly = false,
  onEdit,
  onDeleted,
  ...actions
}: {
  events: EventRecord[];
  canPopulateTestUsers?: boolean;
  readOnly?: boolean;
  onEdit: (event: EventRecord) => void;
  onDeleted: (event: EventRecord) => void;
} & PublicationActions) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = events.find((event) => event.id === selectedId);
  return (
    <>
      <ul id="events-list" className="event-list">
        {events.map((event) => (
          <li key={event.id}>
            <button
              id={`event-open-${event.id}`}
              type="button"
              className="event-list-item"
              aria-haspopup="dialog"
              onClick={() => setSelectedId(event.id)}
            >
              <span className="event-list-top">
                <span className="event-list-title">{event.title}</span>
                <span className="event-badges"><span className={`badge ${event.status === "draft" ? "draft" : ""}`}>
                  {event.archived_at ? "Archived" : (event.status === "draft" && event.scheduled_publish_at != null ? "scheduled" : event.status.replaceAll("_", " "))}
                </span>{event.is_test && <span className="badge">Test</span>}</span>
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
        readOnly={readOnly}
        onClose={() => setSelectedId(null)}
        onEdit={onEdit}
        onDeleted={onDeleted}
        {...actions}
      />}
    </>
  );
}

export function EventDetails({ event, canPopulateTestUsers, readOnly, onClose, onEdit, onDeleted, ...actions }: {
  event: EventRecord;
  canPopulateTestUsers: boolean;
  readOnly: boolean;
  onClose: () => void;
  onEdit: (event: EventRecord) => void;
  onDeleted: (event: EventRecord) => void;
} & PublicationActions) {
  const dialog = useRef<HTMLDialogElement>(null);
  const signupOpensAt = event.published_at ?? event.scheduled_publish_at;
  const signupClosesAt = event.closes_at ?? (
    event.series_id && event.scheduled_publish_at != null
      ? event.scheduled_publish_at + event.duration_hours * 3600
      : null
  );
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
    <dialog id={`event-dialog-${event.id}`} onClick={(event) => { if (isBackdropClick(event)) onClose(); }} ref={dialog} className="event-modal" aria-labelledby={`event-${event.id}`}
      onCancel={(event) => { event.preventDefault(); onClose(); }}>
      <ModalHeader className="event-details-header">
        <h2 id={`event-${event.id}`}>{event.title}</h2>
        <span className="event-badges"><span className={`badge ${event.status === "draft" ? "draft" : ""}`}>
          {event.archived_at ? "Archived" : (event.status === "draft" && event.scheduled_publish_at != null ? "scheduled" : event.status.replaceAll("_", " "))}
        </span>{event.is_test && <span className="badge">Test</span>}</span>
        <div className="event-header-actions">
          {event.status === "assigned" && <SignupDownload event={event} onAccessError={actions.onAccessError} />}
          {!readOnly && (event.status === "open" || event.status === "closing") && <CloseSignups event={event} csrf={actions.csrf} onUpdated={actions.onUpdated} onAccessError={actions.onAccessError} />}
          {event.discord_url && (
            <DiscordLink className="button event-icon-action" url={event.discord_url} label={`View Discord signup for ${event.title}`}>
              <DiscordIcon size={18} />
            </DiscordLink>
          )}
          {!readOnly && event.status === "assigned" && !event.archived_at && <ArchiveEvent event={event} csrf={actions.csrf} onUpdated={actions.onUpdated} onAccessError={actions.onAccessError} />}
          {!readOnly && event.status === "assigned" && <ShareEvent eventId={event.id} csrf={actions.csrf} onAccessError={actions.onAccessError} />}
          {!readOnly && event.status === "assigned" && event.archived_at && <DeleteDiscordMessages event={event} csrf={actions.csrf} onUpdated={actions.onUpdated} onAccessError={actions.onAccessError} />}
          {!readOnly && (event.status === "draft" || event.status === "scheduled") && <PublishEvent event={event} {...actions} />}
          {!readOnly && (event.status === "draft" || event.status === "scheduled" || event.status === "open") && (
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
        <button id={`event-close-${event.id}`} type="button" onClick={onClose} aria-label="Close event" title="Close event" autoFocus>
          <X size={18} aria-hidden="true" />
        </button>
      </ModalHeader>
            <dl className="event-details">
              <EventDateLine label="Event starts" timestamp={event.starts_at} />
              {event.location && <div><dt>Location</dt><dd>{event.location}</dd></div>}
              {signupOpensAt != null && <EventDateLine label="Signup Open" timestamp={signupOpensAt} />}
              <EventDateLine label="Signup Close" timestamp={signupClosesAt} />
            </dl>
            {event.is_test && <p className="notice">Test event: includes {event.test_user_count} simulated signups. Announcements will be marked TEST.</p>}
            <EventTables key={`${event.id}:${event.discord_url}:${event.status}:${event.test_generation ?? ""}`} event={event} csrf={actions.csrf} readOnly={readOnly} onAccessError={actions.onAccessError} />
            {event.status === "closing" && <p role="status" className="notice">
              {event.close_error ?? "Signups are closing. Placements are waiting for Discord's final vote totals."}
            </p>}
            <div className="form-actions">
              {!readOnly && event.status === "assigned" && !event.archived_at && event.discord_url && <DeleteSignupMessage event={event} csrf={actions.csrf} onUpdated={actions.onUpdated} onAccessError={actions.onAccessError} />}
              {!readOnly && canPopulateTestUsers && (event.status === "draft" || event.status === "scheduled" || event.status === "open") && <PopulateTestUsers event={event} csrf={actions.csrf} onUpdated={actions.onUpdated} onAccessError={actions.onAccessError} />}
            </div>
            {event.status === "assigned" && <AssignmentAnnouncement event={event} csrf={actions.csrf} readOnly={readOnly} onAccessError={actions.onAccessError} />}
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
  const timezone = useTimezone();
  return <time dateTime={new Date(timestamp * 1000).toISOString()}>
    {formatTimestamp(timestamp, timezone)}
  </time>;
}
