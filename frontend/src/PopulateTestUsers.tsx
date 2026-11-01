import { useRef, useState } from "react";
import TextField from "@mui/material/TextField";
import ConfirmationDialog from "./ConfirmationDialog";
import { api, errorMessage, mutationOptions, type EventRecord } from "./api";

export default function PopulateTestUsers({ event, csrf, onUpdated, onAccessError }: {
  event: EventRecord; csrf: string;
  onUpdated: (event: EventRecord, message?: string) => void;
  onAccessError: (error: unknown) => boolean;
}) {
  const [open, setOpen] = useState(false);
  const [players, setPlayers] = useState(String(event.test_user_count || Math.min(1000, event.tables.reduce((n, t) => n + t.capacity, 0) + 10)));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inFlight = useRef(false);
  async function populate() {
    if (inFlight.current) return;
    const count = Number(players);
    if (players === "" || !Number.isInteger(count) || count < 0 || count > 1000) {
      setError("Choose a whole number from 0 to 1000."); return;
    }
    inFlight.current = true; setBusy(true); setError("");
    try {
      const value = await api<EventRecord>(`/events/${encodeURIComponent(event.id)}/test-users`, mutationOptions(csrf, { players: count }));
      setOpen(false);
      onUpdated(value, count ? `${count} test players added. Existing real signups are unchanged.` : "Test players removed.");
    } catch (failure) { if (!onAccessError(failure)) setError(errorMessage(failure)); }
    finally { inFlight.current = false; setBusy(false); }
  }
  return <>
    <button type="button" onClick={() => { setError(""); setOpen(true); }}>Populate Test Users</button>
    {open && <ConfirmationDialog title="Populate test users?" busy={busy} error={error}
      status="Adding test signups…" onCancel={() => setOpen(false)} onConfirm={() => void populate()}>
      <p>Adds test players directly to this event's signup list. You can then publish, close signups, and assign players normally. Discord announcements will be marked TEST.</p>
      <TextField label="Test Users" type="number" value={players} disabled={busy} fullWidth
        onChange={(e) => setPlayers(e.target.value)} helperText="Reuses saved test users and their edited names and weights. Use 0 to remove signups; saved profiles remain."
        slotProps={{ inputLabel: { shrink: true }, htmlInput: { min: 0, max: 1000, step: 1 } }} />
    </ConfirmationDialog>}
  </>;
}
