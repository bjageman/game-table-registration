import { useEffect, useState } from "react";
import { api, errorMessage, type EventRecord } from "./api";

interface TableSignups {
  name: string;
  players: { id: string; name: string }[];
}

export default function EventTables({ event, onAccessError, refreshToken = 0, onRefreshingChange }: {
  event: EventRecord;
  refreshToken?: number;
  onRefreshingChange?: (refreshing: boolean) => void;
  onAccessError: (error: unknown) => boolean;
}) {
  const [rows, setRows] = useState<TableSignups[]>();
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!event.discord_url) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      onRefreshingChange?.(true);
      try {
        const result = await api<TableSignups[]>(`/events/${encodeURIComponent(event.id)}/signups`, { signal: controller.signal });
        if (!controller.signal.aborted) { setRows(result); setError(""); }
      } catch (failure) {
        if (!controller.signal.aborted && !onAccessError(failure)) setError(errorMessage(failure));
      } finally {
        if (!controller.signal.aborted) {
          onRefreshingChange?.(false);
          timer = setTimeout(() => void refresh(), 15000);
        }
      }
    }
    void refresh();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [event.id, event.discord_url, attempt, refreshToken, onAccessError, onRefreshingChange]);
  return <>
    {error && <p role="alert" className="error">
      Could not refresh signups. {rows ? "Showing the last loaded list. " : ""}{error}{" "}
      <button type="button" onClick={() => setAttempt((value) => value + 1)}>Retry signups</button>
    </p>}
    <ul className="event-tables" aria-label="Tables">
      {event.tables.map((table) => {
        const players = rows?.find((row) => row.name === table.name)?.players;
        const count = event.discord_url ? players?.length : 0;
        return <li key={table.name} className="event-table">
          <div className="table-heading">
            <h3>{table.name}</h3>
            <span className="table-player-count" aria-label={`${count ?? "Unknown"} signups for ${table.capacity} seats`}>
              {count ?? "—"}/{table.capacity}
            </span>
          </div>
          {players?.length ? <ul className="table-players">
            {players.map((player) => <li key={player.id}>
              <button type="button" className="player-name" aria-disabled="true"
                title="Player editing is coming soon">{player.name}</button>
            </li>)}
          </ul> : <p className="help">{count === 0 ? "No players signed up yet." : error ? "Signups unavailable." : "Loading signups…"}</p>}
        </li>;
      })}
    </ul>
  </>;
}
