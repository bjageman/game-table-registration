import TableTitle from "./TableTitle";
import PlayerProfile from "./PlayerProfile";
import { useEffect, useState } from "react";
import { api, errorMessage, mutationOptions, type EventRecord } from "./api";

interface SignupPlayer { id: string; name: string; display_name?: string; weighting?: number; guaranteed_table?: string | null; guaranteed_seat?: boolean }

export interface TableSignups {
  name: string;
  players: SignupPlayer[];
  waitlist?: SignupPlayer[];
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
  const [actionError, setActionError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [editingWeight, setEditingWeight] = useState<string>();
  const [weight, setWeight] = useState("");
  const [saving, setSaving] = useState(false);
  const hasSignups = event.status === "assigned" || Boolean(event.discord_url) || Boolean(event.is_test);
  async function saveSetting(player: SignupPlayer, change: { weighting?: number; guaranteed_table?: string | null }) {
    if (saving) return;
    setSaving(true); setActionError("");
    try {
      const saved = await api<{ weighting: number; guaranteed_table: string | null; guaranteed_seat: boolean }>(
        `/events/${encodeURIComponent(event.id)}/players/${encodeURIComponent(player.id)}/settings`,
        { ...mutationOptions(csrf, change), method: "PUT" },
      );
      setRows((current) => current?.map((row) => ({ ...row, players: row.players.map((entry) => entry.id === player.id ? { ...entry, ...saved } : entry) })));
      setEditingWeight(undefined);
    } catch (failure) {
      if (!onAccessError(failure)) setActionError(errorMessage(failure));
    } finally { setSaving(false); }
  }
  useEffect(() => {
    if (!hasSignups) return;
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
  }, [event.id, event.discord_url, event.status, event.is_test, event.test_generation, hasSignups, attempt, refreshToken, onAccessError, onRefreshingChange]);
  return <>
    {selectedPlayer && <PlayerProfile key={selectedPlayer.id} player={selectedPlayer} csrf={csrf}
      onSaved={() => setAttempt((value) => value + 1)} onClose={() => setSelectedPlayer(undefined)} onAccessError={onAccessError} />}
    {error && <p role="alert" className="error">
      Could not refresh signups. {rows ? "Showing the last loaded list. " : ""}{error}{" "}
      <button type="button" onClick={() => setAttempt((value) => value + 1)}>Retry signups</button>
    </p>}
    {actionError && <p role="alert" className="error">Could not save player setting. {actionError}</p>}
    <TableColumns event={event} rows={hasSignups ? rows : event.tables.map((t) => ({ name: t.name, players: [] }))} error={error} onSelect={setSelectedPlayer}
      editingWeight={editingWeight} weight={weight} saving={saving} onWeightChange={setWeight}
      onEditWeight={(player, table) => { setEditingWeight(`${player.id}:${table}`); setWeight(String(player.weighting ?? 1)); }}
      onCancelWeight={() => setEditingWeight(undefined)}
      onSaveWeight={(player) => { const value = Number(weight); if (weight.trim() && Number.isFinite(value) && value >= 0.1 && value <= 10) void saveSetting(player, { weighting: value }); else setActionError("Choose a weight from 0.1 to 10."); }}
      onToggleGuarantee={(player, table) => void saveSetting(player, { guaranteed_table: player.guaranteed_table === table ? null : table })} />
  </>;
}

export function TableColumns({ event, rows, error = "", onSelect, editingWeight, weight = "", saving = false, onWeightChange, onEditWeight, onCancelWeight, onSaveWeight, onToggleGuarantee }: {
  event: Pick<EventRecord, "tables" | "status">;
  rows?: TableSignups[];
  error?: string;
  onSelect?: (player: { id: string; name: string }) => void;
  editingWeight?: string;
  weight?: string;
  saving?: boolean;
  onWeightChange?: (value: string) => void;
  onEditWeight?: (player: SignupPlayer, table: string) => void;
  onCancelWeight?: () => void;
  onSaveWeight?: (player: SignupPlayer) => void;
  onToggleGuarantee?: (player: SignupPlayer, table: string) => void;
}) {
  return (
    <ul className="event-tables" aria-label="Tables">
      {event.tables.map((table) => {
        const row = rows?.find((row) => row.name === table.name);
        const players = row?.players;
        const count = rows ? players?.length : undefined;
        return <li key={table.name} className="event-table">
          <div className="table-heading">
            <TableTitle>{table.name}</TableTitle>
            <span className="table-player-count" aria-label={`${count ?? "Unknown"} ${event.status === "assigned" ? "assigned players" : "signups"} for ${table.capacity} seats`}>
              {count ?? "—"}/{table.capacity}
            </span>
          </div>
          {players?.length ? <ul className="table-players">
            {players.map((player) => <li key={player.id} className="table-player-row">
              {event.status === "open" && <button type="button" className="player-guarantee" disabled={saving} aria-pressed={player.guaranteed_table === table.name}
                aria-label={`${player.guaranteed_table === table.name ? "Remove" : "Guarantee"} ${player.display_name || player.name} at ${table.name}`}
                title={player.guaranteed_table === table.name ? "Remove table guarantee" : player.guaranteed_seat && !player.guaranteed_table ? "Profile guarantees a seat at one selected table; click to guarantee this table" : "Guarantee this table"}
                onClick={() => onToggleGuarantee?.(player, table.name)}>{player.guaranteed_table === table.name || (player.guaranteed_seat && !player.guaranteed_table) ? "⭐" : "⚪"}</button>}
              {onSelect ? <button type="button" className="player-name" aria-haspopup="dialog"
                title={player.display_name || player.name} aria-label={player.display_name || player.name}
                onClick={() => onSelect(player)}>{(player.display_name || player.name).slice(0, 20)}{(player.display_name || player.name).length > 20 ? "…" : ""}</button> : (player.display_name || player.name).slice(0, 20)}
              {event.status === "open" && (editingWeight === `${player.id}:${table.name}` ? <form className="player-weight-editor" onSubmit={(submit) => { submit.preventDefault(); onSaveWeight?.(player); }}>
                <input type="number" min="0.1" max="10" step="0.1" aria-label={`Weight for ${player.display_name || player.name}`} value={weight} onChange={(change) => onWeightChange?.(change.target.value)} disabled={saving} autoFocus />
                <button type="submit" disabled={saving}>Save</button><button type="button" onClick={onCancelWeight} disabled={saving}>Cancel</button>
              </form> : <button type="button" className={`player-weight ${(player.weighting ?? 1) < 1 ? "low" : (player.weighting ?? 1) > 1 ? "high" : ""}`}
                title="Edit event weight" aria-label={`Edit weight for ${player.display_name || player.name}: ${(player.weighting ?? 1).toFixed(1)}`} disabled={saving}
                onClick={() => onEditWeight?.(player, table.name)}>{(player.weighting ?? 1).toFixed(1)}</button>)}
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
