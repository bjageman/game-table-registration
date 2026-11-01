import PlayerProfile from "./PlayerProfile";
import { useEffect, useState } from "react";
import { api, errorMessage, type EventRecord } from "./api";

export interface TableSignups {
  name: string;
  players: { id: string; name: string; display_name?: string }[];
  waitlist?: { id: string; name: string; display_name?: string }[];
}

export default function EventTables({ event, csrf, onAccessError, refreshToken = 0, onRefreshingChange }: {
  event: EventRecord;
  csrf: string;
  refreshToken?: number;
  onRefreshingChange?: (refreshing: boolean) => void;
  onAccessError: (error: unknown) => boolean;
}) {
  const [selectedPlayer, setSelectedPlayer] = useState<{ id: string; name: string }>();
  const [rows, setRows] = useState<TableSignups[]>();
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!event.discord_url && !event.is_test) return;
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
          if (event.status !== "assigned") timer = setTimeout(() => void refresh(), 15000);
        }
      }
    }
    void refresh();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [event.id, event.discord_url, event.status, event.is_test, event.test_generation, attempt, refreshToken, onAccessError, onRefreshingChange]);
  return <>
    {selectedPlayer && <PlayerProfile key={selectedPlayer.id} player={selectedPlayer} csrf={csrf}
      onSaved={() => setAttempt((value) => value + 1)} onClose={() => setSelectedPlayer(undefined)} onAccessError={onAccessError} />}
    {error && <p role="alert" className="error">
      Could not refresh signups. {rows ? "Showing the last loaded list. " : ""}{error}{" "}
      <button type="button" onClick={() => setAttempt((value) => value + 1)}>Retry signups</button>
    </p>}
    <TableColumns event={event} rows={event.discord_url || event.is_test ? rows : event.tables.map((t) => ({ name: t.name, players: [] }))} error={error} onSelect={setSelectedPlayer} />
  </>;
}

export function TableColumns({ event, rows, error = "", onSelect }: {
  event: Pick<EventRecord, "tables" | "status">;
  rows?: TableSignups[];
  error?: string;
  onSelect?: (player: { id: string; name: string }) => void;
}) {
  return (
    <ul className="event-tables" aria-label="Tables">
      {event.tables.map((table) => {
        const row = rows?.find((row) => row.name === table.name);
        const players = row?.players;
        const count = rows ? players?.length : undefined;
        return <li key={table.name} className="event-table">
          <div className="table-heading">
            <h3>{table.name}</h3>
            <span className="table-player-count" aria-label={`${count ?? "Unknown"} ${event.status === "assigned" ? "assigned players" : "signups"} for ${table.capacity} seats`}>
              {count ?? "—"}/{table.capacity}
            </span>
          </div>
          {players?.length ? <ul className="table-players">
            {players.map((player) => <li key={player.id}>
              {onSelect ? <button type="button" className="player-name" aria-haspopup="dialog"
                title="View Player Information" onClick={() => onSelect(player)}>{player.display_name || player.name}</button> : player.display_name || player.name}
            </li>)}
          </ul> : <p className="help">{count === 0 ? event.status === "assigned" ? "No players assigned." : "No players signed up yet." : error ? "Signups unavailable." : "Loading signups…"}</p>}
          {event.status === "assigned" && row && <div className="table-waitlist">
            <h4>Waitlist</h4>
            {row.waitlist?.length ? <ol>{row.waitlist.map((player) => <li key={player.id}>
              {onSelect ? <button type="button" className="player-name" aria-haspopup="dialog" onClick={() => onSelect(player)}>{player.display_name || player.name}</button> : player.display_name || player.name}
            </li>)}</ol> : <p className="help">No players waiting.</p>}
          </div>}
        </li>;
      })}
    </ul>
  );
}
