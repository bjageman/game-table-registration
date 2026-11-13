import { useEffect, useRef, useState } from "react";
import { ArrowDownWideNarrow, Download, RefreshCw, Search, Eye, Trash2 } from "lucide-react";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import InputAdornment from "@mui/material/InputAdornment";
import { FormField } from "../../components/FormFields";
import {
  api,
  errorMessage,
  mutationOptions,
  type EventRecord,
  type ModeratorSession,
} from "../../lib/api";
import EventList, { EventDetails } from "./EventList";
import EventForm from "./forms/EventForm";
import LoadingIndicator from "../../components/LoadingIndicator";
import { download } from "../../lib/download";

export interface DashboardProps {
  session: ModeratorSession;
  onAccessError: (error: unknown) => boolean;
}

const sortOptions = [
  { value: "date-asc", label: "Event Date: Earliest First" },
  { value: "date-desc", label: "Event Date: Latest First" },
  { value: "title-asc", label: "Title: A–Z" },
  { value: "title-desc", label: "Title: Z–A" },
] as const;
type SortOrder = typeof sortOptions[number]["value"];
const titleOrder = new Intl.Collator(undefined, { sensitivity: "base", numeric: true });
const scheduleTime = new Intl.DateTimeFormat(undefined, {
  month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit",
});
interface RecurringSeriesRecord { id: string; title: string; frequency: string; time_zone: string; opens_before_hours: number; closes_before_hours: number }

export default function Dashboard({ session, onAccessError }: DashboardProps) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortOrder>("date-asc");
  const [sortAnchor, setSortAnchor] = useState<HTMLElement | null>(null);
  const [exporting, setExporting] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const [showScheduled, setShowScheduled] = useState(true);
  const [events, setEvents] = useState<EventRecord[]>([]);
  const [series, setSeries] = useState<RecurringSeriesRecord[]>([]);
  const [scheduledDetails, setScheduledDetails] = useState<EventRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<EventRecord | undefined>();
  const [notice, setNotice] = useState("");
  const noticeElement = useRef<HTMLParagraphElement>(null);
  const createButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (notice) noticeElement.current?.focus();
  }, [notice]);

  function created(event: EventRecord) {
    setEvents((rows) =>
      [...rows.filter((row) => row.id !== event.id), event].sort(
        (a, b) => a.starts_at - b.starts_at,
      ),
    );
    setCreating(false);
    setEditing(undefined);
    setNotice(
      `Draft saved: ${event.title}. Nothing has been posted to Discord.`,
    );
  }

  function updated(event: EventRecord, notice?: string) {
    setEvents((rows) => rows.map((row) => (row.id === event.id ? event : row)));
    const message = event.status === "assigned" ? "Placements determined" : event.status === "closing" ? "Signups closing" : "Signups published";
    setNotice(notice ?? `${message}: ${event.title}.`);
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

  useEffect(() => {
    const controller = new AbortController();
    api<RecurringSeriesRecord[]>("/recurring-series", { signal: controller.signal })
      .then((rows) => { if (!controller.signal.aborted) setSeries(rows); })
      .catch((failure) => { if (!controller.signal.aborted && !onAccessError(failure)) setError(errorMessage(failure)); });
    return () => controller.abort();
  }, [attempt, onAccessError]);

  async function cancelScheduled(event: EventRecord) {
    try {
      await api(`/events/${event.id}/cancel-scheduled`, mutationOptions(session.csrf));
      setNotice(`Canceled ${event.title} on ${new Date(event.starts_at * 1000).toLocaleString()}.`);
      setAttempt((value) => value + 1);
    } catch (failure) { if (!onAccessError(failure)) setNotice(errorMessage(failure)); }
  }

  async function stopSchedule(row: RecurringSeriesRecord) {
    try {
      await api(`/recurring-series/${row.id}/stop`, mutationOptions(session.csrf));
      setNotice(`Stopped ${row.title}. Upcoming unposted events were removed.`);
      setAttempt((value) => value + 1);
    } catch (failure) { if (!onAccessError(failure)) setNotice(errorMessage(failure)); }
  }


  function refresh() {
    setLoading(true);
    setError("");
    setNotice("");
    setAttempt((value) => value + 1);
  }

  const titleQuery = query.trim().toLocaleLowerCase();
  const visibleEvents = events.filter((event) =>
    event.status !== "scheduled" && (showArchived || !event.archived_at) && event.title.toLocaleLowerCase().includes(titleQuery),
  ).sort((a, b) => {
    const byTitle = titleOrder.compare(a.title, b.title);
    const byDate = a.starts_at - b.starts_at;
    const primary = sort === "date-asc" ? byDate : sort === "date-desc" ? -byDate
      : sort === "title-asc" ? byTitle : -byTitle;
    return primary || byTitle || byDate || a.id.localeCompare(b.id);
  });

  return (
    <section id="events-dashboard" aria-label="Events">
      <div id="events-toolbar" className="section-heading event-toolbar">
        <div className="event-search-controls">
          <FormField id="events-search" type="search" placeholder="Search Events" size="small" value={query}
            onChange={(event) => setQuery(event.target.value)}
            slotProps={{ htmlInput: { "aria-label": "Search events" }, input: {
              startAdornment: <InputAdornment position="start"><Search size={18} aria-hidden="true" /></InputAdornment>,
            } }} />
          <button id="events-sort-button" type="button" className="event-icon-action" aria-label="Sort events" title="Sort Events"
            aria-haspopup="menu" aria-expanded={Boolean(sortAnchor)} aria-controls={sortAnchor ? "event-sort-menu" : undefined}
            onClick={(event) => setSortAnchor(event.currentTarget)}>
            <ArrowDownWideNarrow size={18} aria-hidden="true" />
          </button>
          <button id="events-download-all-button" type="button" className="event-icon-action" aria-label="Download all event signups" title="Download All Event Signups"
            disabled={exporting || loading || Boolean(error)} onClick={() => {
              setExporting(true);
              void download("/exports/signups.csv", "all-event-signups.csv")
                .catch((failure) => { if (!onAccessError(failure)) setNotice(`Could not download signups: ${errorMessage(failure)}`); })
                .finally(() => setExporting(false));
            }}><Download size={18} aria-hidden="true" /></button>
          <Menu id="event-sort-menu" anchorEl={sortAnchor} open={Boolean(sortAnchor)} onClose={() => setSortAnchor(null)}
            slotProps={{ list: { "aria-label": "Sort events" } }}>
            {sortOptions.map((option) => <MenuItem id={`events-sort-${option.value}`} key={option.value} role="menuitemradio" aria-checked={sort === option.value}
              selected={sort === option.value} onClick={() => { setSort(option.value); setSortAnchor(null); }}>{option.label}</MenuItem>)}
          </Menu>
        </div>
        <div className="form-actions">
          {session.organization_role !== "user" &&
          <button
            id="event-create-button"
            ref={createButton}
            className="primary"
            onClick={() => {
              setEditing(undefined);
              setCreating(true);
              setNotice("");
            }}
            disabled={creating || loading || Boolean(error)}
          >
            Create event
          </button>}
          <button
            id="events-refresh-button"
            className="refresh-events-button"
            onClick={refresh}
            disabled={loading || creating}
            aria-label={loading ? "Refreshing…" : "Refresh events"}
            title={loading ? "Refreshing…" : "Refresh events"}
          >
            <RefreshCw size={18} aria-hidden="true" />
          </button>
        </div>
      </div>
      <div className="archive-filter-controls">
        <label className="archive-filter"><input id="events-show-archived" type="checkbox" checked={showArchived} onChange={(event) => setShowArchived(event.target.checked)} /> Archived</label>
        {(series.length > 0 || events.some((event) => event.status === "scheduled")) && <label className="archive-filter"><input id="events-show-scheduled" type="checkbox" checked={showScheduled} onChange={(event) => setShowScheduled(event.target.checked)} /> Scheduled Events</label>}
      </div>
      {notice && (
        <p role="status" className="notice" ref={noticeElement} tabIndex={-1}>
          {notice}
        </p>
      )}
      {creating && (
        <EventForm
          key={editing?.id ?? "new"}
          event={editing}
          csrf={session.csrf}
          onCreated={created}
          onScheduled={(title) => { setCreating(false); setNotice(`Recurring schedule created: ${title}.`); setAttempt((value) => value + 1); }}
          onCancel={() => {
            setCreating(false);
            setEditing(undefined);
            requestAnimationFrame(() => createButton.current?.focus());
          }}
          onAccessError={onAccessError}
        />
      )}
      {loading && <p><LoadingIndicator label="Loading events…" /></p>}
      {error && (
        <div className="panel">
          <p role="alert" className="error">
            {error}
          </p>
          <button onClick={refresh}>Try again</button>
        </div>
      )}
      {!loading && !error && showScheduled && (series.length > 0 || events.some((event) => event.status === "scheduled")) && <section id="scheduled-events-panel" className="panel scheduled-events-panel" aria-label="Scheduled events">
        <div className="scheduled-events-content">
          <h3>Scheduled Events</h3>
          {series.map((row) => <details className="scheduled-event-group" key={row.id}>
            <summary><span>{row.title} - {row.frequency}</span>
              {session.organization_role !== "user" && <button id={`schedule-delete-${row.id}`} type="button" className="delete-schedule-button" onClick={(event) => { event.preventDefault(); event.stopPropagation(); void stopSchedule(row); }}>Delete</button>}
            </summary>
            <div className="scheduled-event-occurrences">
              {events.filter((event) => event.status === "scheduled" && event.series_id === row.id).sort((a, b) => a.starts_at - b.starts_at).slice(0, 4).map((event) => <div key={event.id} className="scheduled-event-row">
                <span className="scheduled-event-times">
                  <span>EVENT: {scheduleTime.format(new Date(event.starts_at * 1000))}</span>
                  <span className="scheduled-event-time-separator" aria-hidden="true"> - </span>
                  <span>SIGNUPS: {scheduleTime.format(new Date((event.scheduled_publish_at ?? 0) * 1000))}</span>
                </span>
                <div className="scheduled-event-actions">
                  <button id={`scheduled-event-view-${event.id}`} type="button" className="event-icon-action" aria-label="View scheduled event" title="View scheduled event" onClick={() => setScheduledDetails(event)}><Eye size={18} aria-hidden="true" /></button>
                  {session.organization_role !== "user" && <button id={`scheduled-event-cancel-${event.id}`} type="button" className="event-icon-action" aria-label="Cancel scheduled event" title="Cancel scheduled event" onClick={() => void cancelScheduled(event)}><Trash2 size={18} aria-hidden="true" /></button>}
                </div>
              </div>)}
              <div className="scheduled-event-row"><span>Timezone: {row.time_zone}</span></div>
            </div>
          </details>)}
        </div>
      </section>}
      {scheduledDetails && <EventDetails
        event={scheduledDetails}
        canPopulateTestUsers={Boolean(session.can_populate_test_users)}
        readOnly={session.organization_role === "user"}
        onClose={() => setScheduledDetails(null)}
        onEdit={(event) => { setScheduledDetails(null); setEditing(event); setCreating(true); }}
        onDeleted={(event) => { setScheduledDetails(null); setEvents((rows) => rows.filter((row) => row.id !== event.id)); }}
        csrf={session.csrf}
        onUpdated={(event) => { updated(event); setScheduledDetails(null); }}
        onUncertain={uncertain}
        onAccessError={onAccessError}
      />}
      {!loading &&
        !error &&
        (visibleEvents.length ? (
          <EventList
            readOnly={session.organization_role === "user"}
            canPopulateTestUsers={Boolean(session.can_populate_test_users)}
            events={visibleEvents}
            onEdit={(event) => {
              setEditing(event);
              setCreating(true);
              setNotice("");
            }}
            onDeleted={(event) => {
              setEvents((rows) => rows.filter((row) => row.id !== event.id));
              if (editing?.id === event.id) {
                setEditing(undefined);
                setCreating(false);
              }
              setNotice(`Draft deleted: ${event.title}.`);
            }}
            csrf={session.csrf}
            onUpdated={updated}
            onUncertain={uncertain}
            onAccessError={onAccessError}
          />
        ) : (
          <div className="panel">
            <h3>{titleQuery ? "No Matching Events" : events.length ? "No Active Events" : "No Events Yet"}</h3>
            {!events.length && !titleQuery && <p>Event drafts and published signups will appear here.</p>}
          </div>
        ))}
    </section>
  );
}
