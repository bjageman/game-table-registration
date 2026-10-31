import { useEffect, useState } from "react";
import { api, mutationOptions, errorMessage, type ScheduleRecord } from "./api";
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
  const [editing, setEditing] = useState<ScheduleRecord>();
  const [busy, setBusy] = useState(false);
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
          onClick={() => {
            setEditing(undefined);
            setCreating(true);
          }}
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
          key={editing?.id ?? "new"}
          initial={editing}
          csrf={csrf}
          onAccessError={onAccessError}
          onCancel={() => setCreating(false)}
          onSaved={(row) => {
            setRows((rs) => [...rs.filter((r) => r.id !== row.id), row]);
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
          <div className="form-actions">
            <button
              disabled={creating || busy}
              onClick={() => {
                setEditing(r);
                setCreating(true);
              }}
            >
              Edit future occurrences
            </button>
            <button
              disabled={creating || busy}
              onClick={async () => {
                if (
                  !window.confirm(
                    `${r.active ? "Pause" : "Resume"} ${r.title}? ${r.active ? "Unpublished occurrences will stop opening; published polls keep their closing jobs." : "Future signup jobs will resume. Expired windows require review."}`,
                  )
                )
                  return;
                setBusy(true);
                setError("");
                try {
                  const updated = await api<ScheduleRecord>(
                    `/schedules/${r.id}/active`,
                    mutationOptions(csrf, {
                      active: !r.active,
                      revision: r.revision,
                    }),
                  );
                  setRows((rs) =>
                    rs.map((v) => (v.id === updated.id ? updated : v)),
                  );
                  onChanged();
                } catch (failure) {
                  if (!onAccessError(failure)) setError(errorMessage(failure));
                } finally {
                  setBusy(false);
                }
              }}
            >
              {r.active ? "Pause schedule" : "Resume schedule"}
            </button>
          </div>
        </article>
      ))}
    </section>
  );
}
