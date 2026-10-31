import { useEffect, useState } from "react";
import { api, errorMessage, type ScheduleRecord } from "./api";
import ScheduleForm from "./ScheduleForm";

export default function Schedules({
  csrf,
  onAccessError,
  onChanged,
}: {
  csrf: string;
  onAccessError: (error: unknown) => boolean;
  onChanged: () => void;
}) {
  const [rows, setRows] = useState<ScheduleRecord[]>([]);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    api<ScheduleRecord[]>("/schedules", { signal: controller.signal })
      .then((v) => {
        if (!controller.signal.aborted) setRows(v);
      })
      .catch((e) => {
        if (!controller.signal.aborted && !onAccessError(e))
          setError(errorMessage(e));
      });
    return () => controller.abort();
  }, [attempt, onAccessError]);
  return (
    <section className="schedule-section" aria-label="Weekly schedules">
      <div className="section-heading">
        <h3>Weekly schedules</h3>
        <button
          type="button"
          disabled={creating}
          onClick={() => setCreating(true)}
        >
          Create weekly schedule
        </button>
      </div>
      {error && (
        <p role="alert" className="error">
          {error}{" "}
          <button
            onClick={() => {
              setError("");
              setAttempt((a) => a + 1);
            }}
          >
            Retry schedules
          </button>
        </p>
      )}
      {creating && (
        <ScheduleForm
          csrf={csrf}
          onAccessError={onAccessError}
          onCancel={() => setCreating(false)}
          onSaved={(row) => {
            setRows((rs) => [...rs, row]);
            setCreating(false);
            onChanged();
          }}
        />
      )}
      {rows.map((r) => (
        <article className="panel" key={r.id}>
          <h4>{r.title}</h4>
          <p>
            {r.active ? "Active" : "Paused"} · {r.timezone} · Every week from{" "}
            {r.first_date} at {r.event_time}
          </p>
          {r.last_error && <p className="error">{r.last_error}</p>}
        </article>
      ))}
    </section>
  );
}
