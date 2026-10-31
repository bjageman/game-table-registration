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
  return (
    <ul className="event-list">
      {events.map((event) => (
        <li key={event.id}>
          <article
            className="panel event-card"
            aria-labelledby={`event-${event.id}`}
          >
            <div className="section-heading">
              <h3 id={`event-${event.id}`}>{event.title}</h3>
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
              {event.opens_at && (
                <div>
                  <dt>Signups open</dt>
                  <dd>{formatTime(event.opens_at)}</dd>
                </div>
              )}
              {event.signup_closes_at && (
                <div>
                  <dt>Signups close</dt>
                  <dd>{formatTime(event.signup_closes_at)}</dd>
                </div>
              )}
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
            <ul className="table-summary" aria-label="Tables">
              {event.tables.map((table) => (
                <li key={table.name}>
                  {table.name} <span>· {table.capacity} seats</span>
                </li>
              ))}
            </ul>
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
                  onEdit={onEdit}
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
          </article>
        </li>
      ))}
    </ul>
  );
}
