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
  event?: EventRecord;
  onCreated: (event: EventRecord) => void;
  onCancel: () => void;
  onAccessError: (error: unknown) => boolean;
}

function initialTime(): Dayjs {
  const current = dayjs();
  const minute =
    current.minute() +
    Number(current.second() > 0 || current.millisecond() > 0);
  return current
    .minute(Math.ceil(minute / 15) * 15)
    .second(0)
    .millisecond(0);
}

export default function EventForm({
  csrf,
  event: draft,
  onCreated,
  onCancel,
  onAccessError,
}: Props) {
  const prefix = useId();
  const [opening, setOpening] = useState<Dayjs | null>(
    draft?.opens_at ? dayjs.unix(draft.opens_at) : initialTime(),
  );
  const [title, setTitle] = useState(draft?.title ?? "");
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
  const closing = opening?.add(Number(duration), "hour") ?? null;
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

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (inFlight.current) return;
    setError("");
    const errors = validateEvent({
      scheduled: true,
      title,
      startsAt: startsAtLocal,
      duration,
      tables,
    });
    if (
      !opening?.isValid() ||
      !closing?.isValid() ||
      !(
        Date.now() < opening.valueOf() &&
        opening.valueOf() < closing.valueOf() &&
        closing.valueOf() < new Date(startsAtLocal).getTime()
      ) ||
      closing.diff(opening, "hour", true) > 768
    ) {
      errors.window =
        "Require now < signup opening < closing < event start, within 32 days.";
    }
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
        draft ? `/events/${draft.id}` : "/events",
        {
          ...mutationOptions(csrf, {
            timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
            opens_at: opening?.toISOString(),
            signup_closes_at: closing?.toISOString(),
            title: title.trim(),
            starts_at: start.toISOString(),
            duration_hours: hours,
            tables: tables.map((table) => ({
              name: table.name.trim(),
              capacity: Number(table.capacity),
            })),
          }),
          method: draft ? "PUT" : "POST",
        },
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
      <h3 id={`${prefix}-heading`}>
        {draft ? "Edit event draft" : "Create event draft"}
      </h3>
      <p>Save the details first. Creating a draft does not post to Discord.</p>
      <form
        noValidate
        onSubmit={(event) => void submit(event)}
        aria-label={draft ? "Edit event" : "Create event"}
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
