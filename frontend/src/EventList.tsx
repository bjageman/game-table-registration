import { isBackdropClick } from "./dialogBackdrop";
import { useEffect, useRef, useState } from "react";
import { Eye, RefreshCw, X } from "lucide-react";
import ArchiveEvent from "./ArchiveEvent";
import ShareEvent from "./ShareEvent";
import DeleteDiscordMessages from "./DeleteDiscordMessages";
import DeleteSignupMessage from "./DeleteSignupMessage";
import EventTables from "./EventTables";
import DiscordLink from "./DiscordLink";
import PopulateTestUsers from "./PopulateTestUsers";
import AssignmentAnnouncement from "./AssignmentAnnouncement";
import SignupDownload from "./SignupDownload";
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
  const title = useRef<HTMLHeadingElement>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const signupOpensAt = event.published_at ?? event.scheduled_publish_at;
  const signupClosesAt = event.closes_at ?? (
    event.series_id && event.scheduled_publish_at != null
      ? event.scheduled_publish_at + event.duration_hours * 3600
      : null
  );
  useEffect(() => {
    const heading = title.current;
    if (!heading) return;
    function fitTitle() {
      if (!heading) return;
      heading.style.removeProperty("font-size");
      if (!window.matchMedia?.("(max-width: 600px)").matches) return;
      const size = parseFloat(getComputedStyle(heading).fontSize);
      if (heading.scrollWidth > heading.clientWidth && heading.clientWidth > 0) {
        heading.style.fontSize = `${Math.max(1, size * heading.clientWidth / heading.scrollWidth - 0.2)}px`;
      }
    }
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(fitTitle) : null;
    observer?.observe(heading);
    window.addEventListener("resize", fitTitle);
    fitTitle();
    return () => { observer?.disconnect(); window.removeEventListener("resize", fitTitle); };
  }, [event.title]);
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
        <h2 ref={title} id={`event-${event.id}`}>{event.title}</h2>
        <span className="event-badges"><span className={`badge ${event.status === "draft" ? "draft" : ""}`}>
          {event.archived_at ? "Archived" : (event.status === "draft" && event.scheduled_publish_at != null ? "scheduled" : event.status.replaceAll("_", " "))}
        </span>{event.is_test && <span className="badge">Test</span>}</span>
        <div className="event-header-actions">
          {event.status === "assigned" && <SignupDownload event={event} onAccessError={actions.onAccessError} />}
          {!readOnly && (event.status === "open" || event.status === "closing") && <CloseSignups event={event} csrf={actions.csrf} onUpdated={actions.onUpdated} onAccessError={actions.onAccessError} />}
          {event.status !== "draft" && event.status !== "scheduled" && event.status !== "assigned" && (
          <button type="button" className="event-icon-action"
            aria-label={refreshing ? "Refreshing signups" : "Refresh signups"}
            title={refreshing ? "Refreshing Signups" : "Refresh Signups"}
            disabled={refreshing}
            onClick={() => setRefreshToken((value) => value + 1)}>
            <RefreshCw size={18} aria-hidden="true" />
          </button>
          )}
          {event.discord_url && (
            <DiscordLink className="button event-icon-action" url={event.discord_url} label={`View Discord signup for ${event.title}`}>
              <Eye size={18} aria-hidden="true" />
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
              {event.location && <div><dt>Location</dt><dd>{event.location}</dd></div>}
              {signupOpensAt != null && (
                <div>
                  <dt>Signup Open</dt>
                  <dd>
                    <time dateTime={new Date(signupOpensAt * 1000).toISOString()}>
                      {formatTime(signupOpensAt)}
                    </time>
                  </dd>
                </div>
              )}
                <div>
                  <dt>Signup Close</dt>
                  <dd>
                    {signupClosesAt != null ? <time
                      dateTime={new Date(signupClosesAt * 1000).toISOString()}
                    >
                      {formatTime(signupClosesAt)}
                    </time> : "-"}
                  </dd>
                </div>
            </dl>
            {event.is_test && <p className="notice">Test event: includes {event.test_user_count} simulated signups. Announcements will be marked TEST.</p>}
            <EventTables key={`${event.id}:${event.discord_url}:${event.status}:${event.test_generation ?? ""}`} event={event} csrf={actions.csrf} readOnly={readOnly} refreshToken={refreshToken} onRefreshingChange={setRefreshing} onAccessError={actions.onAccessError} />
            {event.status === "closing" && <p role="status" className="notice">
              {event.close_error ?? "Signups are closing. Placements are waiting for Discord's final vote totals."}
            </p>}
            <div className="form-actions">
              {!readOnly && event.status === "assigned" && !event.archived_at && event.discord_url && <DeleteSignupMessage event={event} csrf={actions.csrf} onUpdated={actions.onUpdated} onAccessError={actions.onAccessError} />}
              {!readOnly && canPopulateTestUsers && (event.status === "draft" || event.status === "scheduled" || event.status === "open") && <PopulateTestUsers event={event} csrf={actions.csrf} onUpdated={actions.onUpdated} onAccessError={actions.onAccessError} />}
            </div>
            {event.status === "assigned" && <AssignmentAnnouncement event={event} csrf={actions.csrf} readOnly={readOnly} refreshToken={refreshToken} onAccessError={actions.onAccessError} />}
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
