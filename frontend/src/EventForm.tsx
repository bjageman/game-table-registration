import { useId, useRef, useState, type FormEvent } from "react";
import { Plus } from "lucide-react";
import TextField from "@mui/material/TextField";
import useMediaQuery from "@mui/material/useMediaQuery";
import { DatePicker } from "@mui/x-date-pickers/DatePicker";
import { DateTimePicker } from "@mui/x-date-pickers/DateTimePicker";
import { TimePicker } from "@mui/x-date-pickers/TimePicker";
import type { Dayjs } from "dayjs";
import dayjs from "dayjs";
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
  const [startsAtLocal, setStartsAtLocal] = useState("");
  const [mobileDate, setMobileDate] = useState<Dayjs | null>(null);
  const [mobileTime, setMobileTime] = useState(initialTime);
  const [duration, setDuration] = useState("24");
  const [tables, setTables] = useState([{ id: 0, name: "", capacity: "15" }]);
  const nextId = useRef(1);
  const inFlight = useRef(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const isMobile = useMediaQuery("(max-width: 600px)");
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
    if (mobileDate) {
      setStartsAtLocal(
        `${mobileDate.format("YYYY-MM-DD")}T${value.format("HH:mm")}`,
      );
    }
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
    const errors = validateEvent({
      title,
      startsAt: startsAtLocal,
      duration,
      tables,
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
                    timeSteps={{ minutes: 15 }}
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
                  value={startsAt}
                  onChange={updateDesktopStart}
                  referenceDate={mobileTime}
                  format="MMMM D, YYYY h:mm A"
                  ampm
                  timeSteps={{ minutes: 15 }}
                  slotProps={{
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
            <div>
              <TextField
                id={`${prefix}-signup-start`}
                label="Signup starts"
                value="When the event is published"
                fullWidth
                variant="outlined"
                slotProps={{
                  input: { readOnly: true },
                  inputLabel: { shrink: true },
                }}
              />
            </div>
            <div>
              <TextField
                id={`${prefix}-duration`}
                error={Boolean(fieldErrors.duration)}
                helperText={fieldErrors.duration}
                label="Signup duration (hours)"
                type="number"
                value={duration}
                onChange={(event) => setDuration(event.target.value)}
                required
                fullWidth
                variant="outlined"
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
                    error={Boolean(fieldErrors[`name-${table.id}`])}
                    helperText={fieldErrors[`name-${table.id}`]}
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
                    error={Boolean(fieldErrors[`capacity-${table.id}`])}
                    helperText={fieldErrors[`capacity-${table.id}`]}
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
