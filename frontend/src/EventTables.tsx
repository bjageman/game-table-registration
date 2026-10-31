import { useEffect, useState } from "react";
import { api, errorMessage, type EventRecord } from "./api";

interface TableSignups {
  name: string;
  players: { id: string; name: string }[];
}

export default function EventTables({ event, onAccessError }: {
  event: EventRecord;
  onAccessError: (error: unknown) => boolean;
}) {
  const [signups, setSignups] = useState<TableSignups[]>();
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    setSignups(undefined);
    setError("");
    if (!event.discord_url) return;
    const controller = new AbortController();
    api<TableSignups[]>(`/events/${encodeURIComponent(event.id)}/signups`, { signal: controller.signal })
      .then((rows) => { if (!controller.signal.aborted) setSignups(rows); })
      .catch((failure) => {
        if (!controller.signal.aborted && !onAccessError(failure)) setError(errorMessage(failure));
      });
    return () => controller.abort();
  }, [event, attempt, onAccessError]);
  return <>
    {error && <p role="alert" className="error">Could not load signups: {error}{" "}
      <button onClick={() => setAttempt((value) => value + 1)}>Retry signups</button>
    </p>}
    <ul className="event-tables" aria-label="Tables">
      {event.tables.map((table) => {
        const players = signups?.find((row) => row.name === table.name)?.players ?? [];
        return <li key={table.name} className="event-table">
          <h4>{table.name} – {table.capacity} seats</h4>
          {players.length > 0 ? <ul className="table-players">
            {players.map((player) => <li key={player.id}>{player.name}</li>)}
          </ul> : <p className="help">{event.discord_url && !signups
            ? error ? "Signups unavailable." : "Loading signups…"
            : "No players signed up yet."}</p>}
        </li>;
      })}
    </ul>
  </>;
}
