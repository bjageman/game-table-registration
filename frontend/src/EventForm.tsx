import { useId, useRef, useState, type FormEvent } from "react";
import {
  api,
  ApiError,
  errorMessage,
  mutationOptions,
  type EventRecord,
} from "./api";

import { validateEvent } from "./eventValidation";

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
  const [startsAt, setStartsAt] = useState("");
  const [duration, setDuration] = useState("24");
  const [tables, setTables] = useState([{ id: 0, name: "", capacity: "15" }]);
  const nextId = useRef(1);
  const inFlight = useRef(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
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
    const errors = validateEvent({ title, startsAt, duration, tables });
    setFieldErrors(errors);
    if (Object.keys(errors).length) {
      setError([...new Set(Object.values(errors))].join(" "));
      requestAnimationFrame(() =>
        document.getElementById(`${prefix}-${Object.keys(errors)[0]}`)?.focus(),
      );
      return;
    }
    const start = new Date(startsAt);
    const hours = Number(duration);
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

  function attributes(key: string, description?: string) {
    return {
      "aria-invalid": Boolean(fieldErrors[key]),
      "aria-describedby":
        [description, fieldErrors[key] ? `${prefix}-${key}-error` : undefined]
          .filter(Boolean)
          .join(" ") || undefined,
    };
  }
  function fieldError(key: string) {
    return fieldErrors[key] ? (
      <p className="error field-error" id={`${prefix}-${key}-error`}>
        {fieldErrors[key]}
      </p>
    ) : null;
  }

  return (
    <section className="panel form-panel" aria-labelledby={`${prefix}-heading`}>
      <h3 id={`${prefix}-heading`}>Create event draft</h3>
      <p>Save the details first. Creating a draft does not post to Discord.</p>
      <form
        noValidate
        onSubmit={(event) => void submit(event)}
        aria-label="Create event"
      >
        <fieldset disabled={saving}>
          <legend className="sr-only">Event details</legend>
          <label htmlFor={`${prefix}-title`}>Event title</label>
          <input
            id={`${prefix}-title`}
            {...attributes("title")}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            required
            maxLength={100}
            autoFocus
          />
          {fieldError("title")}
          <div className="form-grid">
            <div>
              <label htmlFor={`${prefix}-start`}>Event date and time</label>
              <input
                type="datetime-local"
                id={`${prefix}-start`}
                {...attributes("start", `${prefix}-timezone`)}
                value={startsAt}
                onChange={(event) => setStartsAt(event.target.value)}
                required
              />
              {fieldError("start")}
              <p id={`${prefix}-timezone`} className="help">
                Your timezone: {timezone}. Times are saved with a UTC offset.
              </p>
            </div>
            <div>
              <label htmlFor={`${prefix}-duration`}>
                Signup duration (hours)
              </label>
              <input
                type="number"
                id={`${prefix}-duration`}
                {...attributes("duration")}
                min={1}
                max={768}
                step={1}
                value={duration}
                onChange={(event) => setDuration(event.target.value)}
                required
              />
              {fieldError("duration")}
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
                  {...attributes(`name-${table.id}`)}
                  value={table.name}
                  onChange={(event) =>
                    updateTable(table.id, { name: event.target.value })
                  }
                  required
                  maxLength={35}
                />
                {fieldError(`name-${table.id}`)}
              </div>
              <div>
                <label htmlFor={`${prefix}-capacity-${table.id}`}>
                  Table {index + 1} capacity
                </label>
                <input
                  id={`${prefix}-capacity-${table.id}`}
                  {...attributes(`capacity-${table.id}`)}
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
                {fieldError(`capacity-${table.id}`)}
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
            type="button"
            disabled={tables.length >= 10}
            onClick={() => {
              const row = { id: nextId.current++, name: "", capacity: "15" };
              setTables((rows) => [...rows, row]);
            }}
          >
            Add table
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
