import { useState } from "react";
import TextField from "@mui/material/TextField";
import { DatePicker } from "@mui/x-date-pickers/DatePicker";
import { TimePicker } from "@mui/x-date-pickers/TimePicker";
import { Plus, Minus } from "lucide-react";
import dayjs from "dayjs";
import {
  api,
  mutationOptions,
  errorMessage,
  type ScheduleDraft,
  type ScheduleRecord,
  type OccurrencePreview,
} from "./api";

export default function ScheduleForm({
  csrf,
  initial,
  onSaved,
  onCancel,
  onAccessError,
}: {
  csrf: string;
  initial?: ScheduleRecord;
  onSaved: (value: ScheduleRecord) => void;
  onCancel: () => void;
  onAccessError: (error: unknown) => boolean;
}) {
  const [draft, setDraft] = useState<ScheduleDraft>(
    initial ?? {
      title: "",
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      first_date: dayjs().add(14, "day").format("YYYY-MM-DD"),
      event_time: "19:00",
      opening_days_before: 7,
      opening_time: "12:00",
      closing_days_before: 1,
      closing_time: "12:00",
      tables: [{ name: "", capacity: 15 }],
      skip_dates: [],
    },
  );
  const [rows, setRows] = useState<OccurrencePreview[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  function change(patch: Partial<ScheduleDraft>) {
    setDraft((d) => ({ ...d, ...patch }));
    setRows([]);
  }
  async function act(save: boolean) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      if (save)
        onSaved(
          await api<ScheduleRecord>(
            initial ? `/schedules/${initial.id}` : "/schedules",
            {
              ...mutationOptions(csrf, {
                ...draft,
                ...(initial ? { revision: initial.revision } : {}),
              }),
              method: initial ? "PUT" : "POST",
            },
          ),
        );
      else
        setRows(
          await api<OccurrencePreview[]>(
            initial ? `/schedules/${initial.id}/preview` : "/schedules/preview",
            mutationOptions(csrf, {
              ...draft,
              ...(initial ? { revision: initial.revision } : {}),
            }),
          ),
        );
    } catch (failure) {
      if (!onAccessError(failure)) setError(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }
  function show(timestamp?: number) {
    return timestamp
      ? new Intl.DateTimeFormat(undefined, {
          dateStyle: "medium",
          timeStyle: "short",
          timeZone: draft.timezone,
        }).format(timestamp * 1000)
      : "—";
  }
  return (
    <section className="panel form-panel" aria-label="Weekly schedule editor">
      <h3>Weekly schedule</h3>
      <p>
        {initial
          ? "Changes apply to future unpublished occurrences; individual overrides are preserved."
          : "Confirming activates automatic Discord publication."}{" "}
        Times follow the selected timezone each week.
      </p>
      <fieldset disabled={busy} className="schedule-fields">
        <div className="form-grid">
          <TextField
            label="Schedule title"
            value={draft.title}
            onChange={(e) => change({ title: e.target.value })}
            fullWidth
            slotProps={{
              inputLabel: { shrink: true },
              htmlInput: { maxLength: 100 },
            }}
          />
          <TextField
            label="Timezone"
            value={draft.timezone}
            onChange={(e) => change({ timezone: e.target.value })}
            fullWidth
            slotProps={{ inputLabel: { shrink: true } }}
          />
          <DatePicker
            label="First event date"
            value={dayjs(draft.first_date)}
            onChange={(v) =>
              change({ first_date: v?.format("YYYY-MM-DD") ?? "" })
            }
            slotProps={{
              textField: {
                fullWidth: true,
                slotProps: { inputLabel: { shrink: true } },
              },
            }}
          />
          {(
            [
              ["Event time", "event_time"],
              ["Signup opening time", "opening_time"],
              ["Signup closing time", "closing_time"],
            ] as const
          ).map(([label, key]) => (
            <TimePicker
              key={key}
              label={label}
              value={dayjs(`2000-01-01T${draft[key]}`)}
              onChange={(v) => change({ [key]: v?.format("HH:mm") ?? "" })}
              slotProps={{
                textField: {
                  fullWidth: true,
                  slotProps: { inputLabel: { shrink: true } },
                },
              }}
            />
          ))}
          <TextField
            label="Opening days before event"
            type="number"
            value={draft.opening_days_before}
            onChange={(e) =>
              change({ opening_days_before: Number(e.target.value) })
            }
            slotProps={{
              inputLabel: { shrink: true },
              htmlInput: { min: 0, max: 32 },
            }}
          />
          <TextField
            label="Closing days before event"
            type="number"
            value={draft.closing_days_before}
            onChange={(e) =>
              change({ closing_days_before: Number(e.target.value) })
            }
            slotProps={{
              inputLabel: { shrink: true },
              htmlInput: { min: 0, max: 32 },
            }}
          />
        </div>
        <h4 className="tables-heading">Tables</h4>
        <div className="table-list">
          {draft.tables.map((table, index) => (
            <div className="table-fields" key={index}>
              <TextField
                label={`Weekly table ${index + 1} name`}
                value={table.name}
                onChange={(e) =>
                  change({
                    tables: draft.tables.map((t, i) =>
                      i === index ? { ...t, name: e.target.value } : t,
                    ),
                  })
                }
                fullWidth
                slotProps={{
                  inputLabel: { shrink: true },
                  htmlInput: { maxLength: 35 },
                }}
              />
              <TextField
                label="Capacity"
                type="number"
                value={table.capacity}
                onChange={(e) =>
                  change({
                    tables: draft.tables.map((t, i) =>
                      i === index
                        ? { ...t, capacity: Number(e.target.value) }
                        : t,
                    ),
                  })
                }
                fullWidth
                slotProps={{
                  inputLabel: { shrink: true },
                  htmlInput: { min: 1, max: 999 },
                }}
              />
              {draft.tables.length > 1 && (
                <button
                  type="button"
                  aria-label={`Remove weekly table ${index + 1}`}
                  onClick={() =>
                    change({
                      tables: draft.tables.filter((_, i) => i !== index),
                    })
                  }
                >
                  <Minus size={18} />
                </button>
              )}
            </div>
          ))}
        </div>
        <button
          type="button"
          aria-label="Add weekly table"
          disabled={draft.tables.length >= 10}
          onClick={() =>
            change({ tables: [...draft.tables, { name: "", capacity: 15 }] })
          }
        >
          <Plus size={18} />
        </button>
      </fieldset>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {rows.length > 0 && (
        <div className="schedule-preview">
          <h4>Next eight weeks · {draft.timezone}</h4>
          {rows.map((r) => (
            <div key={r.date} className="notice">
              <strong>
                {r.date} {r.action ? `· ${r.action}` : ""}
              </strong>
              {r.skipped ? (
                <p>Skipped</p>
              ) : (
                <p>
                  Opens {show(r.opens_at)} · Closes {show(r.signup_closes_at)} ·
                  Event {show(r.starts_at)}
                </p>
              )}
              {r.error && <p className="error">{r.error}</p>}
              <label>
                <input
                  type="checkbox"
                  checked={r.skipped}
                  disabled={busy || ["preserved", "cancel"].includes(r.action ?? "")}
                  onChange={(e) => {
                    const skipped = e.target.checked;
                    setDraft((d) => ({
                      ...d,
                      skip_dates: skipped
                        ? [...d.skip_dates, r.date]
                        : d.skip_dates.filter((v) => v !== r.date),
                    }));
                    setRows((rs) =>
                      rs.map((row) =>
                        row.date === r.date ? { ...row, skipped } : row,
                      ),
                    );
                  }}
                />{" "}
                Skip this week
              </label>
            </div>
          ))}
        </div>
      )}
      <div className="form-actions">
        <button type="button" disabled={busy} onClick={() => void act(false)}>
          Preview dates
        </button>
        {rows.length > 0 && (
          <button
            type="button"
            className="primary"
            disabled={
              busy ||
              rows.some(
                (r) => r.error && !r.skipped && r.action !== "preserved",
              )
            }
            onClick={() => void act(true)}
          >
            {initial ? "Confirm future changes" : "Confirm weekly schedule"}
          </button>
        )}
        <button type="button" disabled={busy} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </section>
  );
}
