import { useId, useRef, useState, type FormEvent } from "react";
import { Plus } from "lucide-react";
import TextField from "@mui/material/TextField";
import useMediaQuery from "@mui/material/useMediaQuery";
import { DatePicker } from "@mui/x-date-pickers/DatePicker";
import { DateTimePicker } from "@mui/x-date-pickers/DateTimePicker";
import { TimePicker } from "@mui/x-date-pickers/TimePicker";
import type { Dayjs } from "dayjs";
import dayjs from "dayjs";
import { api, errorMessage, mutationOptions, type EventRecord } from "./api";

interface Props {
  csrf: string;
  onCreated: (event: EventRecord) => void;
  onCancel: () => void;
  onAccessError: (error: unknown) => boolean;
}

function initialTime(): Dayjs {
  const current = dayjs();
  const minute =
    current.minute() + Number(current.second() > 0 || current.millisecond() > 0);
  return current.minute(Math.ceil(minute / 15) * 15).second(0).millisecond(0);
}

export default function EventForm({
  csrf,
  onCreated,
  onCancel,
  onAccessError,
}: Props) {
  const prefix = useId();
  const [title, setTitle] = useState("");
  const [startsAt, setStartsAt] = useState<Dayjs | null>(null);
  const [mobileTime, setMobileTime] = useState(initialTime);
  const [duration, setDuration] = useState("24");
  const [tables, setTables] = useState([{ id: 0, name: "", capacity: "15" }]);
  const nextId = useRef(1);
  const inFlight = useRef(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const isMobile = useMediaQuery("(max-width: 600px)");
  function updateDesktopStart(value: Dayjs | null) {
    setStartsAt(value);
    if (value) setMobileTime(value);
  }

  function updateMobileDate(value: Dayjs | null) {
    if (!value) {
      setStartsAt(null);
      return;
    }
    const time = startsAt ?? mobileTime;
    setStartsAt(
      value
        .hour(time.hour())
        .minute(time.minute())
        .second(0)
        .millisecond(0),
    );
  }

  function updateMobileTime(value: Dayjs | null) {
    if (!value) return;
    setMobileTime(value);
    setStartsAt((current) =>
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

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (inFlight.current) return;
    setError("");
    const start = startsAt?.toDate() ?? null;
    const hours = Number(duration);
    if (!title.trim()) {
      setError("Enter an event title.");
      return;
    }
    if (!start || Number.isNaN(start.getTime())) {
      setError("Enter a valid event date and time.");
      return;
    }
    if (start.getTime() <= Date.now() + hours * 3600000) {
      setError(
        "The event must start after the signup window ends. Choose a later time or a shorter signup duration.",
      );
      return;
    }
    if (tables.some((table) => !table.name.trim())) {
      setError("Enter a name for every table.");
      return;
    }
    if (
      new Set(tables.map((table) => table.name.trim().toLowerCase())).size !==
      tables.length
    ) {
      setError("Table names must be unique.");
      return;
    }
    inFlight.current = true;
    setSaving(true);
    try {
      const result = await api<EventRecord>(
        "/events",
        mutationOptions(csrf, {
          title: title.trim(),
          starts_at: start.toISOString(),
          duration_hours: hours,
          tables: tables.map((table) => ({
            name: table.name.trim(),
            capacity: Number(table.capacity),
          })),
        }),
      );
      onCreated(result);
    } catch (failure) {
      if (!onAccessError(failure)) setError(errorMessage(failure));
    } finally {
      inFlight.current = false;
      setSaving(false);
    }
  }

  return (
    <section className="panel form-panel" aria-labelledby={`${prefix}-heading`}>
      <h3 id={`${prefix}-heading`}>Create event draft</h3>
      <p>Save the details first. Creating a draft does not post to Discord.</p>
      <form onSubmit={(event) => void submit(event)} aria-label="Create event">
        <fieldset disabled={saving}>
          <legend className="sr-only">Event details</legend>
          <TextField
            id={`${prefix}-title`}
            label="Event title"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            required
            autoFocus
            fullWidth
            variant="outlined"
            sx={{ mb: 3 }}
            slotProps={{
              inputLabel: { shrink: true },
              htmlInput: { maxLength: 100 },
            }}
          />
          <div className="form-grid event-schedule-fields">
            <div className="date-time-fields">
              {isMobile ? (
                <div className="mobile-date-time-fields">
                  <DatePicker
                    label="Event starts"
                    value={startsAt}
                    onChange={updateMobileDate}
                    format="MMMM D, YYYY"
                    slotProps={{
                      textField: {
                        fullWidth: true,
                        required: true,
                        helperText: `Timezone: ${timezone}`,
                        slotProps: { inputLabel: { shrink: true } },
                      },
                    }}
                  />
                  <TimePicker
                    label="Event time"
                    value={startsAt ?? mobileTime}
                    onChange={updateMobileTime}
                    ampm
                    timeSteps={{ minutes: 15 }}
                    slotProps={{
                      textField: {
                        fullWidth: true,
                        required: true,
                        helperText: "Defaults to the current time.",
                        slotProps: { inputLabel: { shrink: true } },
                      },
                    }}
                  />
                </div>
              ) : (
                <DateTimePicker
                  label="Event starts"
                  value={startsAt}
                  onChange={updateDesktopStart}
                  referenceDate={mobileTime}
                  format="MMMM D, YYYY h:mm A"
                  ampm
                  timeSteps={{ minutes: 15 }}
                  slotProps={{
                    textField: {
                      fullWidth: true,
                      required: true,
                      helperText: `Timezone: ${timezone}. Times are saved with the correct UTC offset.`,
                      slotProps: { inputLabel: { shrink: true } },
                    },
                  }}
                />
              )}
            </div>
            <div>
              <TextField
                id={`${prefix}-signup-start`}
                label="Signup starts"
                value="When the event is published"
                fullWidth
                variant="outlined"
                helperText="Signups open as soon as you publish."
                slotProps={{
                  input: { readOnly: true },
                  inputLabel: { shrink: true },
                }}
              />
            </div>
            <div>
              <TextField
                id={`${prefix}-duration`}
                label="Signup duration (hours)"
                type="number"
                value={duration}
                onChange={(event) => setDuration(event.target.value)}
                required
                fullWidth
                variant="outlined"
                helperText="Starts when you publish. Signups must close before the event."
                slotProps={{
                  inputLabel: { shrink: true },
                  htmlInput: { min: 1, max: 768, step: 1 },
                }}
              />
            </div>
          </div>
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
                    label={`Table ${index + 1} name`}
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
                    label={`Table ${index + 1} capacity`}
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
                <button
                  type="button"
                  disabled={tables.length === 1}
                  aria-label={`Remove table ${index + 1}`}
                  onClick={() =>
                    setTables((rows) => rows.filter((row) => row.id !== table.id))
                  }
                >
                  −
                </button>
              </div>
            ))}
          </div>
          <button
            className="add-table-button"
            type="button"
            aria-label="Add table"
            title="Add table"
            disabled={tables.length >= 10}
            onClick={() =>
              setTables((rows) => [
                ...rows,
                { id: nextId.current++, name: "", capacity: "15" },
              ])
            }
          >
            <Plus size={18} aria-hidden="true" />
          </button>
        </fieldset>
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <div className="form-actions">
          <button className="primary" type="submit" disabled={saving}>
            {saving ? "Saving draft…" : "Save draft"}
          </button>
          <button type="button" onClick={onCancel} disabled={saving}>
            Cancel
          </button>
        </div>
      </form>
    </section>
  );
}
