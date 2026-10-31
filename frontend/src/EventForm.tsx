import { useId, useRef, useState, type FormEvent } from "react";
import { Plus } from "lucide-react";
import { DateTimePicker } from "@mui/x-date-pickers/DateTimePicker";
import type { Dayjs } from "dayjs";
import { api, errorMessage, mutationOptions, type EventRecord } from "./api";

interface Props {
  csrf: string;
  onCreated: (event: EventRecord) => void;
  onCancel: () => void;
  onAccessError: (error: unknown) => boolean;
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
  const [duration, setDuration] = useState("24");
  const [tables, setTables] = useState([{ id: 0, name: "", capacity: "15" }]);
  const nextId = useRef(1);
  const inFlight = useRef(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;

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
          <label htmlFor={`${prefix}-title`}>Event title</label>
          <input
            id={`${prefix}-title`}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            required
            maxLength={100}
            autoFocus
          />
          <div className="form-grid event-schedule-fields">
            <div className="date-time-fields">
              <DateTimePicker
                label="Event starts"
                value={startsAt}
                onChange={(value) => setStartsAt(value)}
                format="MMMM D, YYYY h:mm A"
                ampm
                timeSteps={{ minutes: 15 }}
                slotProps={{
                  textField: {
                    fullWidth: true,
                    required: true,
                    helperText: `Timezone: ${timezone}. Times are saved with the correct UTC offset.`,
                  },
                }}
              />
            </div>
            <div>
              <label htmlFor={`${prefix}-signup-start`}>Signup starts</label>
              <output id={`${prefix}-signup-start`} className="schedule-value">
                When the event is published
              </output>
              <p className="help">Signups open as soon as you publish.</p>
            </div>
            <div>
              <label htmlFor={`${prefix}-duration`}>
                Signup duration (hours)
              </label>
              <input
                type="number"
                id={`${prefix}-duration`}
                min={1}
                max={768}
                step={1}
                value={duration}
                onChange={(event) => setDuration(event.target.value)}
                required
              />
              <p className="help">
                Starts when you publish. Signups must close before the event.
              </p>
            </div>
          </div>
          <div className="section-heading">
            <h4>Tables</h4>
            <span className="help">{tables.length} of 10</span>
          </div>
          {tables.map((table, index) => (
            <div className="table-fields" key={table.id}>
              <div>
                <label htmlFor={`${prefix}-name-${table.id}`}>
                  Table {index + 1} name
                </label>
                <input
                  id={`${prefix}-name-${table.id}`}
                  value={table.name}
                  onChange={(event) =>
                    updateTable(table.id, { name: event.target.value })
                  }
                  required
                  maxLength={35}
                />
              </div>
              <div>
                <label htmlFor={`${prefix}-capacity-${table.id}`}>
                  Table {index + 1} capacity
                </label>
                <input
                  id={`${prefix}-capacity-${table.id}`}
                  type="number"
                  min={1}
                  max={999}
                  step={1}
                  value={table.capacity}
                  onChange={(event) =>
                    updateTable(table.id, { capacity: event.target.value })
                  }
                  required
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
                Remove
              </button>
            </div>
          ))}
          <button
            className="add-table-button"
            type="button"
            disabled={tables.length >= 10}
            onClick={() =>
              setTables((rows) => [
                ...rows,
                { id: nextId.current++, name: "", capacity: "15" },
              ])
            }
          >
            <Plus size={18} aria-hidden="true" />
            Add Table
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
