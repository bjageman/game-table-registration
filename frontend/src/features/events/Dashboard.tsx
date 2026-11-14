import { useTimezone, formatTimestamp } from "../../lib/timezone";
import { useEffect, useRef, useState } from "react";
import { ArrowDownWideNarrow, Download, RefreshCw, Search, Eye, Trash2, Pencil } from "lucide-react";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import InputAdornment from "@mui/material/InputAdornment";
import { FormField } from "../../components/FormFields";
import {
  api,
  errorMessage,
  mutationOptions,
  type EventRecord,
  type RecurringSeriesRecord,
  type ModeratorSession,
} from "../../lib/api";
import EventList, { EventDetails } from "./EventList";
import EventForm from "./forms/EventForm";
import LoadingIndicator from "../../components/LoadingIndicator";
import { download } from "../../lib/download";
import ConfirmationDialog from "../../components/ConfirmationDialog";

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

export default function Dashboard({ session, onAccessError }: DashboardProps) {
  const timezone = useTimezone();
  const scheduleTime = new Intl.DateTimeFormat(undefined, { timeZone: timezone, month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit" });
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortOrder>("date-asc");
  const [sortAnchor, setSortAnchor] = useState<HTMLElement | null>(null);
  const [exporting, setExporting] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const [showScheduled, setShowScheduled] = useState(true);
  const [events, setEvents] = useState<EventRecord[]>([]);
  const [series, setSeries] = useState<RecurringSeriesRecord[]>([]);
  const [deletingSchedule, setDeletingSchedule] = useState<RecurringSeriesRecord>();
  const [cancelingScheduled, setCancelingScheduled] = useState<EventRecord>();
  const [scheduleBusy, setScheduleBusy] = useState(false);
  const [scheduleError, setScheduleError] = useState("");
  const scheduleMutation = useRef(false);
  const [scheduledDetails, setScheduledDetails] = useState<EventRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [creating, setCreating] = useState(false);
  const [editingSeries, setEditingSeries] = useState<RecurringSeriesRecord>();
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
    setEditingSeries(undefined);
    setNotice(
      `${event.status === "scheduled" ? "Scheduled event" : "Draft"} saved: ${event.title}. Nothing has been posted to Discord.`,
    );
  }

  function updated(event: EventRecord, notice?: string) {
    setEvents((rows) => rows.map((row) => (row.id === event.id ? event : row)));
    const message = event.assignment_publication_pending ? "Assignments are waiting for Discord delivery" : event.status === "review" ? "Assignments ready for review" : event.status === "assigned" ? "Placements determined" : event.status === "closing" ? "Signups closing" : "Signups published";
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
    if (scheduleMutation.current) return;
    scheduleMutation.current = true; setScheduleBusy(true); setScheduleError("");
    try {
      await api(`/events/${event.id}/cancel-scheduled`, mutationOptions(session.csrf));
      setCancelingScheduled(undefined);
      setNotice(`Canceled ${event.title} on ${formatTimestamp(event.starts_at, timezone)}.`);
      setAttempt((value) => value + 1);
    } catch (failure) { if (!onAccessError(failure)) setScheduleError(errorMessage(failure)); }
    finally { scheduleMutation.current = false; setScheduleBusy(false); }
  }

  async function stopSchedule(row: RecurringSeriesRecord) {
    if (scheduleMutation.current) return;
    scheduleMutation.current = true;
    setScheduleBusy(true); setScheduleError("");
    try {
      await api(`/recurring-series/${row.id}/stop`, mutationOptions(session.csrf));
      setDeletingSchedule(undefined);
      setNotice(`Stopped ${row.title}. Upcoming unposted events were removed.`);
      setAttempt((value) => value + 1);
    } catch (failure) { if (!onAccessError(failure)) setScheduleError(errorMessage(failure)); }
    finally { scheduleMutation.current = false; setScheduleBusy(false); }
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
              setEditingSeries(undefined);
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
          key={editingSeries?.id ?? editing?.id ?? "new"}
          event={editing}
          series={editingSeries}
          csrf={session.csrf}
          onCreated={created}
          onScheduled={(title) => { setCreating(false); setNotice(`Recurring schedule ${editingSeries ? "updated" : "created"}: ${title}.`); setEditingSeries(undefined); setAttempt((value) => value + 1); }}
          onCancel={() => {
            setCreating(false);
            setEditing(undefined);
            setEditingSeries(undefined);
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
              {session.organization_role !== "user" && <div className="scheduled-event-actions">
                <button id={`schedule-edit-${row.id}`} type="button" disabled={creating} onClick={(event) => { event.preventDefault(); event.stopPropagation(); setEditing(undefined); setEditingSeries(row); setCreating(true); setNotice(""); }}>Edit</button>
                <button id={`schedule-delete-${row.id}`} type="button" className="delete-schedule-button" onClick={(event) => { event.preventDefault(); event.stopPropagation(); setScheduleError(""); setDeletingSchedule(row); }}>Delete</button></div>}
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
                  {session.organization_role !== "user" && <button id={`scheduled-event-edit-${event.id}`} type="button" className="event-icon-action" disabled={creating} aria-label="Edit scheduled event" title="Edit scheduled event" onClick={() => { setEditingSeries(undefined); setEditing(event); setCreating(true); setNotice(""); }}><Pencil size={18} aria-hidden="true" /></button>}
                  {session.organization_role !== "user" && <button id={`scheduled-event-cancel-${event.id}`} type="button" className="event-icon-action" aria-label="Cancel scheduled event" title="Cancel scheduled event" onClick={() => { setScheduleError(""); setCancelingScheduled(event); }}><Trash2 size={18} aria-hidden="true" /></button>}
                </div>
              </div>)}
            </div>
          </details>)}
        </div>
      </section>}
      {cancelingScheduled && <ConfirmationDialog id="scheduled-event-cancel-dialog" title="Cancel scheduled event?"
        busy={scheduleBusy} error={scheduleError} status="Canceling…"
        onCancel={() => setCancelingScheduled(undefined)} onConfirm={() => void cancelScheduled(cancelingScheduled)}>
        <p>Are you sure you want to cancel {cancelingScheduled.title} on {formatTimestamp(cancelingScheduled.starts_at, timezone)}? Only this occurrence will be removed; the recurring schedule will continue.</p>
      </ConfirmationDialog>}
      {deletingSchedule && <ConfirmationDialog id="schedule-delete-dialog" title="Delete recurring event?"
        busy={scheduleBusy} error={scheduleError} status="Deleting…"
        onCancel={() => setDeletingSchedule(undefined)} onConfirm={() => void stopSchedule(deletingSchedule)}>
        <p>Are you sure you want to delete {deletingSchedule.title}? Its recurring schedule and upcoming unposted events will be removed.</p>
      </ConfirmationDialog>}
      {scheduledDetails && <EventDetails
        event={scheduledDetails}
        canPopulateTestUsers={Boolean(session.can_populate_test_users)}
        readOnly={session.organization_role === "user"}
        onClose={() => setScheduledDetails(null)}
        onEdit={(event) => { setScheduledDetails(null); setEditingSeries(undefined); setEditing(event); setCreating(true); }}
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
              setEditingSeries(undefined);
              setEditing(event);
              setCreating(true);
              setNotice("");
            }}
            onDeleted={(event) => {
              setEvents((rows) => rows.filter((row) => row.id !== event.id));
              if (editing?.id === event.id) {
                setEditing(undefined);
                setEditingSeries(undefined);
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
          </div>
        ))}
    </section>
  );
}
