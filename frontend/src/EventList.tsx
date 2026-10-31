import RecoverEvent from "./RecoverEvent";
import DraftActions from "./DraftActions";
import type { EventRecord } from "./api";
import PublishEvent, { type PublicationActions } from "./PublishEvent";

export function formatTime(timestamp: number, timezone?: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "long",
    timeZone: timezone,
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
                <dt>Timezone</dt>
                <dd>
                  {event.timezone ??
                    Intl.DateTimeFormat().resolvedOptions().timeZone}
                </dd>
              </div>
              {event.schedule_id && (
                <div>
                  <dt>Occurrence</dt>
                  <dd>
                    {event.occurrence_date}
                    {event.overridden ? " · overridden" : ""}
                  </dd>
                </div>
              )}
              <div>
                <dt>Event starts</dt>
                <dd>
                  <time
                    dateTime={new Date(event.starts_at * 1000).toISOString()}
                  >
                    {formatTime(event.starts_at, event.timezone)}
                  </time>
                </dd>
              </div>
              {event.opens_at && (
                <div>
                  <dt>Signups open</dt>
                  <dd>{formatTime(event.opens_at, event.timezone)}</dd>
                </div>
              )}
              {event.signup_closes_at && (
                <div>
                  <dt>Signups close</dt>
                  <dd>{formatTime(event.signup_closes_at, event.timezone)}</dd>
                </div>
              )}
              {!event.opens_at && (
                <div>
                  <dt>Signup duration</dt>
                  <dd>{event.duration_hours} hours from publication</dd>
                </div>
              )}
              {event.closes_at !== null && !event.signup_closes_at && (
                <div>
                  <dt>Signups close</dt>
                  <dd>
                    <time
                      dateTime={new Date(event.closes_at * 1000).toISOString()}
                    >
                      {formatTime(event.closes_at, event.timezone)}
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
                Check Discord before taking further action. This event is held
                for review; publication will not be retried automatically.
              </p>
            )}
            {["draft", "scheduled", "paused", "open"].includes(
              event.status,
            ) && (
              <div className="form-actions draft-actions">
                {event.status === "draft" && (
                  <PublishEvent event={event} {...actions} />
                )}
                <DraftActions
                  event={event}
                  csrf={actions.csrf}
                  onEdit={onEdit}
                  onDeleted={onDeleted}
                  onAccessError={actions.onAccessError}
                />
              </div>
            )}
            {event.status === "open" && event.live_signup_count != null && (
              <p>
                Signup preview: {event.live_signup_count} players (may be
                incomplete).
              </p>
            )}
            {event.signup_count != null && (
              <p>
                Final voter snapshot: {event.signup_count} players. Lottery
                assignments are pending.
              </p>
            )}
            {event.status === "needs_review" && (
              <RecoverEvent
                event={event}
                csrf={actions.csrf}
                onUpdated={actions.onUpdated}
                onAccessError={actions.onAccessError}
              />
            )}
            {event.recovery_audit?.some(
              (entry) => entry.accepted_late_votes,
            ) && (
              <p className="notice">
                A moderator accepted later votes after a missed deadline.
              </p>
            )}
            {event.last_error && <p className="notice">{event.last_error}</p>}
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
