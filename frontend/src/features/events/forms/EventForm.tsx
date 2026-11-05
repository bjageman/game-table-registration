import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Plus } from "lucide-react";
import TextField from "@mui/material/TextField";
import MenuItem from "@mui/material/MenuItem";
import Tooltip from "@mui/material/Tooltip";
import useMediaQuery from "@mui/material/useMediaQuery";
import { DatePicker } from "@mui/x-date-pickers/DatePicker";
import { DateTimePicker } from "@mui/x-date-pickers/DateTimePicker";
import { TimePicker } from "@mui/x-date-pickers/TimePicker";
import { renderTimeViewClock } from "@mui/x-date-pickers/timeViewRenderers";
import type { Dayjs } from "dayjs";
import dayjs from "dayjs";
import {
  api,
  ApiError,
  errorMessage,
  mutationOptions,
  type EventRecord,
  type EventTemplateRecord,
} from "../../../lib/api";
import { validateEvent, validateTemplate } from "./eventValidation";
import TemplatePicker from "./TemplatePicker";

interface Props {
  csrf: string;
  event?: EventRecord;
  onCreated: (event: EventRecord) => void;
  onScheduled?: (title: string) => void;
  onCancel: () => void;
  onAccessError: (error: unknown) => boolean;
}

function initialTime(): Dayjs {
  return dayjs().add(1, "hour").startOf("hour");
}

export default function EventForm({
  csrf,
  event: draft,
  onCreated,
  onScheduled,
  onCancel,
  onAccessError,
}: Props) {
  const prefix = useId();
  const [title, setTitle] = useState(draft?.title ?? "");
  const [description, setDescription] = useState(draft?.description ?? "");
  const [location, setLocation] = useState(draft?.location ?? "");
  const [startsAt, setStartsAt] = useState<Dayjs | null>(
    draft ? dayjs.unix(draft.starts_at) : null,
  );
  const [startsAtLocal, setStartsAtLocal] = useState(
    draft ? dayjs.unix(draft.starts_at).format("YYYY-MM-DDTHH:mm") : "",
  );
  const [mobileDate, setMobileDate] = useState<Dayjs | null>(
    draft ? dayjs.unix(draft.starts_at) : null,
  );
  const [mobileTime, setMobileTime] = useState(() =>
    draft
      ? dayjs()
          .hour(dayjs.unix(draft.starts_at).hour())
          .minute(dayjs.unix(draft.starts_at).minute())
      : initialTime(),
  );
  const [duration, setDuration] = useState(String(draft?.duration_hours ?? 24));
  const [manualClosesBefore, setManualClosesBefore] = useState(draft?.closes_at != null ? String(Math.round((draft.starts_at - draft.closes_at) / 3600)) : draft ? "" : "24");
  const [scheduled, setScheduled] = useState(Boolean(draft?.scheduled_publish_at));
  const [frequency, setFrequency] = useState("once");
  const [opensBefore, setOpensBefore] = useState("72");
  const [closesBefore, setClosesBefore] = useState(String(draft?.duration_hours ?? 24));
  const [tables, setTables] = useState(
    draft
      ? draft.tables.map((table, id) => ({
          id,
          name: table.name,
          capacity: String(table.capacity),
        }))
      : [{ id: 0, name: "", capacity: "15" }],
  );
  const nextId = useRef(tables.length);
  const pendingTableFocus = useRef<number | null>(null);
  const scheduleFields = useRef<HTMLDivElement>(null);
  const inFlight = useRef(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [templates, setTemplates] = useState<EventTemplateRecord[]>([]);
  const [choosingTemplate, setChoosingTemplate] = useState(false);
  const [templateNotice, setTemplateNotice] = useState("");
  const isMobile = useMediaQuery("(max-width: 600px)");
  useEffect(() => {
    const controller = new AbortController();
    api<EventTemplateRecord[]>("/templates", { signal: controller.signal })
      .then((result) => { if (!controller.signal.aborted) setTemplates(result); })
      .catch((failure) => { if (!controller.signal.aborted && !onAccessError(failure)) setError(errorMessage(failure)); });
    return () => controller.abort();
  }, [onAccessError]);
  useEffect(() => {
    if (pendingTableFocus.current === null) return;
    document.getElementById(`${prefix}-name-${pendingTableFocus.current}`)?.focus();
    pendingTableFocus.current = null;
  }, [tables, prefix]);

  function addTable() {
    if (inFlight.current || tables.length >= 10) return;
    const id = nextId.current++;
    pendingTableFocus.current = id;
    setTables((rows) => [...rows, { id, name: "", capacity: "15" }]);
  }

  function handleTableEnter(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "Enter" || event.nativeEvent.isComposing || event.keyCode === 229) return;
    event.preventDefault();
    if (!event.repeat) addTable();
  }

  function updateDesktopStart(value: Dayjs | null) {
    setStartsAt(value);
    setStartsAtLocal(value?.isValid() ? value.format("YYYY-MM-DDTHH:mm") : "");
    if (value) setMobileTime(value);
  }

  function updateMobileDate(value: Dayjs | null) {
    if (!value) {
      setMobileDate(null);
      setStartsAt(null);
      setStartsAtLocal("");
      return;
    }
    setMobileDate(value);
    setStartsAtLocal(
      `${value.format("YYYY-MM-DD")}T${mobileTime.format("HH:mm")}`,
    );
    const time = mobileTime;
    setStartsAt(
      value.hour(time.hour()).minute(time.minute()).second(0).millisecond(0),
    );
  }

  function updateMobileTime(value: Dayjs | null) {
    if (!value) return;
    setMobileTime(value);
    if (mobileDate) {
      setStartsAtLocal(
        `${mobileDate.format("YYYY-MM-DD")}T${value.format("HH:mm")}`,
      );
    }
    setStartsAt(
      (current) =>
        current
          ?.hour(value.hour())
          .minute(value.minute())
          .second(0)
          .millisecond(0) ?? null,
    );
  }

  function updateTable(
    id: number,
    patch: Partial<{ name: string; capacity: string }>,
  ) {
    setTables((rows) =>
      rows.map((row) => (row.id === id ? { ...row, ...patch } : row)),
    );
  }

  function loadTemplate(template: EventTemplateRecord) {
    setTitle(template.title);
    setDescription(template.description ?? "");
    setLocation(template.location ?? "");
    setDuration(String(template.duration_hours));
    setClosesBefore(String(template.duration_hours));
    setTables(template.tables.map((table, id) => ({ id, name: table.name, capacity: String(table.capacity) })));
    nextId.current = template.tables.length;
    setFieldErrors({});
    setError("");
    setTemplateNotice(`Loaded template: ${template.title}.`);
    setChoosingTemplate(false);
  }

  async function saveTemplate() {
    if (inFlight.current) return;
    setError(""); setTemplateNotice("");
    const errors = validateTemplate({ title, duration, tables });
    setFieldErrors(errors);
    if (Object.keys(errors).length) {
      setError([...new Set(Object.values(errors))].join(" "));
      requestAnimationFrame(() => document.getElementById(`${prefix}-${Object.keys(errors)[0]}`)?.focus());
      return;
    }
    inFlight.current = true;
    setSaving(true);
    try {
      const saved = await api<EventTemplateRecord>("/templates", mutationOptions(csrf, {
        title: title.trim(),
        description: description.trim(),
        location: location.trim(),
        duration_hours: Number(duration),
        tables: tables.map((table) => ({ name: table.name.trim(), capacity: Number(table.capacity) })),
      }));
      setTemplates((current) => [saved, ...current]);
      setTemplateNotice(`Template saved: ${saved.title}.`);
    } catch (failure) {
      if (!onAccessError(failure)) setError(errorMessage(failure));
    } finally {
      inFlight.current = false;
      setSaving(false);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (inFlight.current) return;
    setError("");
    const errors = validateEvent({
      title,
      startsAt: startsAtLocal,
      duration: scheduled ? String(Number(opensBefore) - Number(closesBefore)) : duration,
      tables,
      explicitClosing: !scheduled,
    });
    setFieldErrors(errors);
    if (Object.keys(errors).length) {
      setError([...new Set(Object.values(errors))].join(" "));
      requestAnimationFrame(() =>
        document.getElementById(`${prefix}-${Object.keys(errors)[0]}`)?.focus(),
      );
      return;
    }
    const start = new Date(startsAtLocal);
    const hours = scheduled ? Number(opensBefore) - Number(closesBefore) : 0;
    if (!scheduled && manualClosesBefore.trim()) {
      const close = Number(manualClosesBefore);
      if (!Number.isInteger(close) || close < 1 || close > 767 || start.getTime() - close * 3600000 <= Date.now()) {
        setError("Choose whole hours before the event so the signup closing time is still in the future.");
        return;
      }
    }
    if (scheduled) {
      const open = Number(opensBefore);
      const close = Number(closesBefore);
      if (!Number.isInteger(open) || !Number.isInteger(close) || open > 768 || close < 1 || close >= open) {
        setError("Choose whole-hour offsets with signups opening before they close.");
        return;
      }
      const opening = new Date(start.getTime() - open * 3600000);
      const now = new Date();
      if (opening.getTime() <= now.getTime()) {
        const format = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "long" });
        setError(`Open signup of ${format.format(opening)} needs to start after the current time ${format.format(now)}.`);
        return;
      }
    }
    inFlight.current = true;
    setSaving(true);
    try {
      const result = await api<EventRecord | { id: string; title: string }>(
        frequency !== "once" ? "/recurring-series" : draft ? `/events/${draft.id}` : "/events",
        {
          ...mutationOptions(csrf, {
            title: title.trim(),
            description: description.trim(),
            location: location.trim(),
            starts_at: start.toISOString(),
            duration_hours: hours,
            ...(scheduled ? { opens_before_hours: Number(opensBefore), closes_before_hours: Number(closesBefore) } : { closes_before_hours: manualClosesBefore.trim() ? Number(manualClosesBefore) : null }),
            ...(frequency !== "once" ? {
              frequency,
              time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone,
              opens_before_hours: Number(opensBefore),
              closes_before_hours: Number(closesBefore),
            } : {}),
            tables: tables.map((table) => ({
              name: table.name.trim(),
              capacity: Number(table.capacity),
            })),
          }),
          method: draft ? "PUT" : "POST",
        },
      );
      if (frequency !== "once") onScheduled?.(result.title);
      else onCreated(result as EventRecord);
    } catch (failure) {
      if (!onAccessError(failure)) {
        setError(errorMessage(failure));
        if (failure instanceof ApiError && failure.issues.length) {
          const fields: Record<string, string> = {};
          for (const issue of failure.issues) {
            const path = issue.loc.filter((part) => part !== "body");
            const key =
              path[0] === "tables" &&
              typeof path[1] === "number" &&
              tables[path[1]]
                ? `${path[2]}-${tables[path[1]].id}`
                : ({ starts_at: "start", duration_hours: "duration" }[
                    String(path[0])
                  ] ?? String(path[0]));
            fields[key] = issue.msg;
          }
          setFieldErrors(fields);
        }
      }
    } finally {
      inFlight.current = false;
      setSaving(false);
    }
  }

  return (
    <section className="panel form-panel" aria-labelledby={`${prefix}-heading`}>
      <div className="section-heading template-heading">
        <h3 id={`${prefix}-heading`}>{draft ? "Edit Event Draft" : !scheduled ? "Create Draft Event" : frequency === "once" ? "Create Scheduled Event" : "Create Recurring Scheduled Event"}</h3>
        {templates.length > 0 && <button type="button" className="text-link" onClick={() => setChoosingTemplate(true)}>Load From Template</button>}
      </div>
      {choosingTemplate && <TemplatePicker templates={templates} onSelect={loadTemplate} onClose={() => setChoosingTemplate(false)} />}
      <form
        noValidate
        onSubmit={(event) => void submit(event)}
        aria-label={draft ? "Edit event" : "Create event"}
      >
        <fieldset disabled={saving}>
          <legend className="sr-only">Event details</legend>
          <div className="event-title-start-row">
          <TextField
            id={`${prefix}-title`}
            error={Boolean(fieldErrors.title)}
            helperText={fieldErrors.title}
            label="Event title"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            required
            autoFocus
            fullWidth
            variant="outlined"
            slotProps={{
              inputLabel: { shrink: true },
              htmlInput: { maxLength: 100 },
            }}
          />
            <div className="date-time-fields" ref={scheduleFields}>
              {isMobile ? (
                <div className="mobile-date-time-fields">
                  <DatePicker
                    label="Event starts"
                    slotProps={{
                      textField: {
                        id: `${prefix}-start`,
                        error: Boolean(fieldErrors.start),
                        helperText: fieldErrors.start,
                        fullWidth: true,
                        required: true,
                        slotProps: { inputLabel: { shrink: true } },
                      },
                    }}
                    value={startsAt}
                    onChange={updateMobileDate}
                    format="MMMM D, YYYY"
                  />
                  <TimePicker
                    label="Event time"
                    value={mobileTime}
                    onChange={updateMobileTime}
                    ampm
                    minutesStep={15}
                    viewRenderers={{
                      hours: renderTimeViewClock,
                      minutes: renderTimeViewClock,
                    }}
                    slotProps={{
                      textField: {
                        id: `${prefix}-time`,
                        fullWidth: true,
                        required: true,
                        slotProps: { inputLabel: { shrink: true } },
                      },
                    }}
                  />
                </div>
              ) : (
                <DateTimePicker
                  label="Event starts"
                  onOpen={() => {
                    scheduleFields.current?.scrollIntoView({
                      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
                        ? "instant"
                        : "smooth",
                      block: "start",
                      inline: "nearest",
                    });
                  }}
                  value={startsAt}
                  onChange={updateDesktopStart}
                  referenceDate={mobileTime}
                  format="MMMM D, YYYY h:mm A"
                  ampm
                  minutesStep={15}
                  viewRenderers={{
                    hours: renderTimeViewClock,
                    minutes: renderTimeViewClock,
                  }}
                  slotProps={{
                    desktopPaper: {
                      sx: {
                        maxHeight: "calc(100dvh - 32px)",
                        overflowY: "auto",
                      },
                    },
                    textField: {
                      id: `${prefix}-start`,
                      fullWidth: true,
                      required: true,
                      error: Boolean(fieldErrors.start),
                      helperText: fieldErrors.start,
                      slotProps: { inputLabel: { shrink: true } },
                    },
                  }}
                />
              )}
            </div>
          </div>
          <div className="event-scheduling-options">
          <label className="scheduled-event-checkbox"><input type="checkbox" checked={scheduled} onChange={(event) => { setScheduled(event.target.checked); if (!event.target.checked) setFrequency("once"); }} /> Scheduled Event</label>
          <div className={`event-scheduling-inputs ${!scheduled ? "single" : ""}`}>
          {!scheduled && <TextField label="Signups Close Before Event (hours)" type="number" value={manualClosesBefore} onChange={(event) => setManualClosesBefore(event.target.value)} fullWidth slotProps={{ htmlInput: { min: 1, max: 767, step: 1 } }} />}
          {scheduled && <div className="form-grid event-schedule-fields">
            <Tooltip title="Open before event (hours)" arrow>
            <TextField
              id={`${prefix}-opens-before`}
              label="Open before event (hours)"
              type="number"
              value={opensBefore}
              onChange={(event) => setOpensBefore(event.target.value)}
              fullWidth
              slotProps={{ inputLabel: { title: "Open before event (hours)" }, htmlInput: { min: 2, max: 768, step: 1 } }}
            />
            </Tooltip>
            <Tooltip title="Close before event (hours)" arrow>
            <TextField
              id={`${prefix}-closes-before`}
              label="Close before event (hours)"
              type="number"
              value={closesBefore}
              onChange={(event) => {
                setClosesBefore(event.target.value);
                setDuration(event.target.value);
              }}
              error={Boolean(fieldErrors.duration)}
              helperText={fieldErrors.duration}
              fullWidth
              required
              slotProps={{ inputLabel: { title: "Close before event (hours)" }, htmlInput: { min: 1, max: 768, step: 1 } }}
            />
            </Tooltip>
            {!draft && <TextField select id={`${prefix}-frequency`} label="Repeat" value={frequency} onChange={(event) => setFrequency(event.target.value)} fullWidth>
              <MenuItem value="once">Does not repeat</MenuItem>
              <MenuItem value="daily">Daily</MenuItem>
              <MenuItem value="weekly">Weekly</MenuItem>
              <MenuItem value="monthly">Monthly</MenuItem>
            </TextField>}
          </div>}
          </div>
          </div>
          <TextField
            id={`${prefix}-description`}
            label="Description"
            placeholder="React with the number for every table you would attend. Remove your reaction to withdraw from that table. This is a lottery entry, not a guaranteed seat. Only reactions received before signups close count."
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            multiline
            minRows={3}
            fullWidth
            sx={{ mt: 1, mb: 3 }}
            slotProps={{ inputLabel: { shrink: true }, htmlInput: { maxLength: 300 } }}
          />
          <TextField
            id={`${prefix}-location`}
            label="Location"
            placeholder="Venue or address (optional)"
            value={location}
            onChange={(event) => setLocation(event.target.value)}
            fullWidth
            sx={{ mb: 1 }}
            slotProps={{ inputLabel: { shrink: true }, htmlInput: { maxLength: 200 } }}
          />
          <div className="section-heading tables-heading">
            <h4>Tables</h4>
            <span className="help">{tables.length} of 10</span>
          </div>
          <div className="table-list">
            {tables.map((table, index) => (
              <div className="table-fields" key={table.id}>
                <div>
                  <TextField
                    id={`${prefix}-name-${table.id}`}
                    error={Boolean(fieldErrors[`name-${table.id}`])}
                    helperText={fieldErrors[`name-${table.id}`]}
                    label={`Table ${index + 1} name`}
                    onKeyDown={handleTableEnter}
                    value={table.name}
                    onChange={(event) =>
                      updateTable(table.id, { name: event.target.value })
                    }
                    required
                    fullWidth
                    variant="outlined"
                    slotProps={{
                      inputLabel: { shrink: true },
                      htmlInput: { maxLength: 35 },
                    }}
                  />
                </div>
                <div>
                  <TextField
                    id={`${prefix}-capacity-${table.id}`}
                    error={Boolean(fieldErrors[`capacity-${table.id}`])}
                    helperText={fieldErrors[`capacity-${table.id}`]}
                    label={`Table ${index + 1} capacity`}
                    onKeyDown={handleTableEnter}
                    type="number"
                    value={table.capacity}
                    onChange={(event) =>
                      updateTable(table.id, { capacity: event.target.value })
                    }
                    required
                    fullWidth
                    variant="outlined"
                    slotProps={{
                      inputLabel: { shrink: true },
                      htmlInput: { min: 1, max: 999, step: 1 },
                    }}
                  />
                </div>
                {tables.length > 1 && (
                  <button
                    type="button"
                    aria-label={`Remove table ${index + 1}`}
                    onClick={() =>
                      setTables((rows) =>
                        rows.filter((row) => row.id !== table.id),
                      )
                    }
                  >
                    −
                  </button>
                )}
              </div>
            ))}
          </div>
          <button
            className="add-table-button"
            type="button"
            aria-label="Add table"
            title="Add table"
            disabled={tables.length >= 10}
            onClick={addTable}
          >
            <Plus size={18} aria-hidden="true" />
          </button>
        </fieldset>
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        {templateNotice && <p role="status" className="notice">{templateNotice}</p>}
        <div className="form-actions">
          <button className="primary" type="submit" disabled={saving}>
            {saving ? "Saving…" : frequency === "once" ? "Save draft" : "Create schedule"}
          </button>
          <button type="button" onClick={() => void saveTemplate()} disabled={saving}>
            {saving ? "Saving template…" : "Save as Template"}
          </button>
          <button type="button" onClick={onCancel} disabled={saving}>
            Cancel
          </button>
        </div>
      </form>
    </section>
  );
}
