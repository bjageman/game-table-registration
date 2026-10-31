import PlayerProfile from "./PlayerProfile";
import { useEffect, useState } from "react";
import { api, errorMessage, type EventRecord } from "./api";

interface TableSignups {
  name: string;
  players: { id: string; name: string }[];
  waitlist?: { id: string; name: string }[];
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
          if (event.status !== "assigned") timer = setTimeout(() => void refresh(), 15000);
        }
      }
    }
    void refresh();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [event.id, event.discord_url, event.status, attempt, refreshToken, onAccessError, onRefreshingChange]);
  return <>
    {selectedPlayer && <PlayerProfile key={selectedPlayer.id} player={selectedPlayer} csrf={csrf}
      onClose={() => setSelectedPlayer(undefined)} onAccessError={onAccessError} />}
    {error && <p role="alert" className="error">
      Could not refresh signups. {rows ? "Showing the last loaded list. " : ""}{error}{" "}
      <button type="button" onClick={() => setAttempt((value) => value + 1)}>Retry signups</button>
    </p>}
    <ul className="event-tables" aria-label="Tables">
      {event.tables.map((table) => {
        const row = rows?.find((row) => row.name === table.name);
        const players = row?.players;
        const count = event.discord_url ? players?.length : 0;
        return <li key={table.name} className="event-table">
          <div className="table-heading">
            <h3>{table.name}</h3>
            <span className="table-player-count" aria-label={`${count ?? "Unknown"} ${event.status === "assigned" ? "assigned players" : "signups"} for ${table.capacity} seats`}>
              {count ?? "—"}/{table.capacity}
            </span>
          </div>
          {players?.length ? <ul className="table-players">
            {players.map((player) => <li key={player.id}>
              <button type="button" className="player-name" aria-haspopup="dialog"
                title="View Player Information" onClick={() => setSelectedPlayer(player)}>{player.name}</button>
            </li>)}
          </ul> : <p className="help">{count === 0 ? event.status === "assigned" ? "No players assigned." : "No players signed up yet." : error ? "Signups unavailable." : "Loading signups…"}</p>}
          {event.status === "assigned" && row && <div className="table-waitlist">
            <h4>Waitlist</h4>
            {row.waitlist?.length ? <ol>{row.waitlist.map((player) => <li key={player.id}>
              <button type="button" className="player-name" aria-haspopup="dialog" onClick={() => setSelectedPlayer(player)}>{player.name}</button>
            </li>)}</ol> : <p className="help">No players waiting.</p>}
          </div>}
        </li>;
      })}
    </ul>
  </>;
}
