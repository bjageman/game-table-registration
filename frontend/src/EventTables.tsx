import TableTitle from "./TableTitle";
import PlayerProfile from "./PlayerProfile";
import { useEffect, useRef, useState } from "react";
import { api, errorMessage, mutationOptions, type EventRecord } from "./api";
import LoadingIndicator from "./LoadingIndicator";
import ConfirmationDialog from "./ConfirmationDialog";
import { isBackdropClick } from "./dialogBackdrop";
import { X } from "lucide-react";

interface SignupPlayer { id: string; name: string; display_name?: string; weighting?: number; guaranteed_table?: string | null; guaranteed_seat?: boolean }
type SortColumn = "guarantee" | "player" | "weight";
type SortState = { column: SortColumn; descending: boolean };

function isGuaranteedAtTable(player: SignupPlayer, table: string): boolean {
  return player.guaranteed_table === table || Boolean(player.guaranteed_seat && !player.guaranteed_table);
}

export interface TableSignups {
  name: string;
  players: SignupPlayer[];
  waitlist?: SignupPlayer[];
}

export default function EventTables({ event, csrf, readOnly = false, onAccessError, refreshToken = 0, onRefreshingChange }: {
  event: EventRecord;
  csrf: string;
  readOnly?: boolean;
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
  const [addingTable, setAddingTable] = useState<string>();
  const [playerQuery, setPlayerQuery] = useState("");
  const [availablePlayers, setAvailablePlayers] = useState<{ discord_id: string; discord_name: string; real_name: string }[]>([]);
  const [playersLoading, setPlayersLoading] = useState(false);
  const [removing, setRemoving] = useState<SignupPlayer>();
  const addDialog = useRef<HTMLDialogElement>(null);
  const hasSignups = event.status === "open" || event.status === "closing" || event.status === "assigned" || Boolean(event.discord_url) || Boolean(event.is_test);
  const canEditSignups = !readOnly && (event.status === "draft" || event.status === "open");
  const canRemoveSignups = !readOnly && (canEditSignups || event.status === "assigned");
  const normalizedQuery = playerQuery.trim().toLocaleLowerCase();
  const suggestions = normalizedQuery ? availablePlayers.filter((player) =>
    `${player.discord_name} ${player.real_name} ${player.discord_id}`.toLocaleLowerCase().includes(normalizedQuery),
  ).slice(0, 30) : [];
  function closeAddPlayer() {
    if (saving) return;
    setAddingTable(undefined);
    setPlayerQuery("");
  }
  useEffect(() => {
    const dialog = addDialog.current;
    if (addingTable) dialog?.showModal();
    return () => { if (dialog?.open) dialog.close(); };
  }, [addingTable]);
  useEffect(() => {
    if (!addingTable) return;
    let active = true;
    api<{ discord_id: string; discord_name: string; real_name: string }[]>("/players")
      .then((players) => { if (active) setAvailablePlayers(players); })
      .catch((failure) => { if (active && !onAccessError(failure)) setActionError(errorMessage(failure)); })
      .finally(() => { if (active) setPlayersLoading(false); });
    return () => { active = false; };
  }, [addingTable, onAccessError]);
  async function addPlayer(player: { discord_id: string; discord_name: string; real_name: string }) {
    if (!addingTable || saving) return;
    setSaving(true); setActionError("");
    try {
      await api(`/events/${encodeURIComponent(event.id)}/manager-players/${encodeURIComponent(player.discord_id)}`,
        { ...mutationOptions(csrf, { table: addingTable, name: player.discord_name }), method: "PUT" });
      const signupPlayer = { id: player.discord_id, name: player.discord_name };
      setRows((current) => {
        const value = current ?? event.tables.map((table) => ({ name: table.name, players: [] }));
        return value.map((row) => row.name === addingTable && !row.players.some((entry) => entry.id === signupPlayer.id)
          ? { ...row, players: [...row.players, signupPlayer] } : row);
      });
      setAddingTable(undefined); setPlayerQuery("");
      setAttempt((value) => value + 1);
    } catch (failure) {
      if (!onAccessError(failure)) setActionError(errorMessage(failure));
    } finally { setSaving(false); }
  }
  async function removePlayer(player: SignupPlayer) {
    setSaving(true); setActionError("");
    try {
      await api(`/events/${encodeURIComponent(event.id)}/manager-players/${encodeURIComponent(player.id)}`,
        { ...mutationOptions(csrf), method: "DELETE" });
      setRows((current) => current?.map((row) => ({ ...row, players: row.players.filter((entry) => entry.id !== player.id) })));
      setRemoving(undefined);
      setAttempt((value) => value + 1);
    } catch (failure) {
      if (!onAccessError(failure)) setActionError(errorMessage(failure));
    } finally { setSaving(false); }
  }
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
    {addingTable && <dialog ref={addDialog} className="event-modal" aria-labelledby="add-player-heading"
      onCancel={(event) => { event.preventDefault(); closeAddPlayer(); }}
      onClick={(event) => { if (isBackdropClick(event)) closeAddPlayer(); }}>
      <div className="event-modal-header">
        <h2 id="add-player-heading">Add a player to {addingTable}</h2>
        <button type="button" disabled={saving} aria-label="Close add player" title="Close" onClick={closeAddPlayer}><X size={18} aria-hidden="true" /></button>
      </div>
      <div className="add-player-search">
        <label htmlFor="add-player-query">Search players</label>
        <input id="add-player-query" type="search" autoFocus autoComplete="off" placeholder="Name or Discord ID"
          role="combobox" aria-autocomplete="list" aria-expanded={suggestions.length > 0} aria-controls="add-player-suggestions"
          value={playerQuery} onChange={(change) => setPlayerQuery(change.target.value)} />
        {playersLoading ? <p><LoadingIndicator label="Loading players…" /></p> : normalizedQuery ? suggestions.length ?
          <ul id="add-player-suggestions" className="add-player-results" role="listbox" aria-label="Suggested players">
            {suggestions.map((player) => <li key={player.discord_id} role="option" aria-selected="false">
              <button type="button" disabled={saving} onClick={() => void addPlayer(player)}>
                <strong>{player.real_name || player.discord_name}</strong>
                <span>{player.real_name ? `@${player.discord_name} · ` : ""}{player.discord_id}</span>
              </button>
            </li>)}
          </ul> : <p className="help">No known players match “{playerQuery}”.</p>
          : <p className="help">Type a name or Discord ID to see known players.</p>}
      </div>
      <div className="form-actions"><button type="button" disabled={saving} onClick={closeAddPlayer}>Cancel</button></div>
    </dialog>}
    {removing && <ConfirmationDialog title="Remove player from signups?" busy={saving} error="" onCancel={() => setRemoving(undefined)} onConfirm={() => void removePlayer(removing)}>
      <p>Remove {removing.display_name || removing.name} from this event’s signups? They will not be notified.</p>
    </ConfirmationDialog>}
    {error && <p role="alert" className="error">
      Could not refresh signups. {rows ? "Showing the last loaded list. " : ""}{error}{" "}
      <button type="button" onClick={() => setAttempt((value) => value + 1)}>Retry signups</button>
    </p>}
    {actionError && <p role="alert" className="error">{actionError}</p>}
    <TableColumns event={event} rows={hasSignups ? rows : rows ?? event.tables.map((t) => ({ name: t.name, players: [] }))} error={error} onSelect={readOnly ? undefined : setSelectedPlayer}
      canEditSignups={canEditSignups} canRemoveSignups={canRemoveSignups} onAddPlayer={(table) => { setPlayersLoading(true); setActionError(""); setAddingTable(table); }} onRemovePlayer={setRemoving}
      editingWeight={editingWeight} weight={weight} saving={saving} readOnly={readOnly} onWeightChange={setWeight}
      onEditWeight={(player, table) => { setEditingWeight(`${player.id}:${table}`); setWeight(String(player.weighting ?? 1)); }}
      onCancelWeight={() => setEditingWeight(undefined)}
      onSaveWeight={(player) => { const value = Number(weight); if (weight.trim() && Number.isFinite(value) && value >= 0.1 && value <= 10) { if (value === (player.weighting ?? 1)) setEditingWeight(undefined); else void saveSetting(player, { weighting: value }); } else setActionError("Choose a weight from 0.1 to 10."); }}
      onToggleGuarantee={(player, table) => void saveSetting(player, { guaranteed_table: player.guaranteed_table === table ? null : table })} />
  </>;
}

export function TableColumns({ event, rows, error = "", onSelect, editingWeight, weight = "", saving = false, readOnly = false, onWeightChange, onEditWeight, onCancelWeight, onSaveWeight, onToggleGuarantee, canEditSignups = false, canRemoveSignups = false, onAddPlayer, onRemovePlayer }: {
  event: Pick<EventRecord, "tables" | "status">;
  rows?: TableSignups[];
  error?: string;
  onSelect?: (player: { id: string; name: string }) => void;
  editingWeight?: string;
  weight?: string;
  saving?: boolean;
  readOnly?: boolean;
  onWeightChange?: (value: string) => void;
  onEditWeight?: (player: SignupPlayer, table: string) => void;
  onCancelWeight?: () => void;
  onSaveWeight?: (player: SignupPlayer) => void;
  onToggleGuarantee?: (player: SignupPlayer, table: string) => void;
  canEditSignups?: boolean;
  canRemoveSignups?: boolean;
  onAddPlayer?: (table: string) => void;
  onRemovePlayer?: (player: SignupPlayer) => void;
}) {
  const [sorts, setSorts] = useState<Record<string, SortState>>({});
  function sortTable(table: string, column: SortColumn) {
    setSorts((current) => ({
      ...current,
      [table]: {
        column,
        descending: current[table]?.column === column ? !current[table].descending : false,
      },
    }));
  }
  return (
    <ul className="event-tables" aria-label="Tables">
      {event.tables.map((table) => {
        const row = rows?.find((row) => row.name === table.name);
        const players = row?.players;
        const count = rows ? players?.length : undefined;
        const sort = sorts[table.name];
        const sortedPlayers = players && sort && event.status === "open" ? [...players].sort((a, b) => {
          const difference = sort.column === "guarantee"
            ? Number(isGuaranteedAtTable(b, table.name)) - Number(isGuaranteedAtTable(a, table.name))
            : sort.column === "weight"
              ? (a.weighting ?? 1) - (b.weighting ?? 1)
              : (a.display_name || a.name).localeCompare(b.display_name || b.name, undefined, { sensitivity: "base" });
          return sort.descending ? -difference : difference;
        }) : players;
        const header = (column: SortColumn, label: string, accessibleLabel: string) => <button type="button" className="table-player-sort"
          aria-label={`Sort ${table.name} by ${accessibleLabel}${sort?.column === column ? `, ${sort.descending ? "descending" : "ascending"}` : ""}`}
          aria-pressed={sort?.column === column} onClick={() => sortTable(table.name, column)}>
          {label}{sort?.column === column && <span aria-hidden="true">{sort.descending ? "▼" : "▲"}</span>}
        </button>;
        return <li key={table.name} className="event-table">
          <div className="table-heading">
            <TableTitle>{table.name}</TableTitle>
            <span className="table-player-count" aria-label={`${count ?? "Unknown"} ${event.status === "assigned" ? "assigned players" : "signups"} for ${table.capacity} seats`}>
              {count ?? "—"}/{table.capacity}
            </span>
          </div>
          {event.status === "open" && <div className={`table-player-header${readOnly ? " read-only" : ""}`}>
            {!readOnly && header("guarantee", "⭐", "guarantee")}{readOnly ? <span>Player</span> : header("player", "Player", "player")}{readOnly ? <span>Wt</span> : header("weight", "Wt", "weight")}
          </div>}
          {players?.length ? <ul className="table-players">
            {sortedPlayers?.map((player) => <li key={player.id} className={event.status === "open" ? `table-player-row${readOnly ? " read-only" : ""}` : "table-assigned-player"}>
              {event.status === "open" && !readOnly && <button type="button" className="player-guarantee" disabled={saving} aria-pressed={player.guaranteed_table === table.name}
                aria-label={`${player.guaranteed_table === table.name ? "Remove" : "Guarantee"} ${player.display_name || player.name} at ${table.name}`}
                title={player.guaranteed_table === table.name ? "Remove table guarantee" : player.guaranteed_seat && !player.guaranteed_table ? "Profile guarantees a seat at one selected table; click to guarantee this table" : "Guarantee this table"}
                onClick={() => onToggleGuarantee?.(player, table.name)}>{isGuaranteedAtTable(player, table.name) ? "⭐" : "⚪"}</button>}
              {onSelect ? <button type="button" className="player-name" aria-haspopup="dialog"
                title={player.display_name || player.name} aria-label={player.display_name || player.name}
                onClick={() => onSelect(player)}>{event.status === "open" ? <>{(player.display_name || player.name).slice(0, 26)}{(player.display_name || player.name).length > 26 ? "…" : ""}</> : player.display_name || player.name}</button> : event.status === "open" ? (player.display_name || player.name).slice(0, 26) : player.display_name || player.name}
              {event.status === "open" && (readOnly ? <span className="player-weight">{(player.weighting ?? 1).toFixed(1)}</span> : editingWeight === `${player.id}:${table.name}` ? <form className="player-weight-editor" onSubmit={(submit) => { submit.preventDefault(); onSaveWeight?.(player); }}>
                <input type="text" inputMode="decimal" aria-label={`Weight for ${player.display_name || player.name}`} value={weight} onChange={(change) => onWeightChange?.(change.target.value)}
                  onBlur={() => onSaveWeight?.(player)} onKeyDown={(key) => { if (key.key === "Escape") { key.preventDefault(); onCancelWeight?.(); } }} disabled={saving} autoFocus />
              </form> : <button type="button" className={`player-weight ${(player.weighting ?? 1) < 1 ? "low" : (player.weighting ?? 1) > 1 ? "high" : ""}`}
                title="Edit event weight" aria-label={`Edit weight for ${player.display_name || player.name}: ${(player.weighting ?? 1).toFixed(1)}`} disabled={saving}
                onClick={() => onEditWeight?.(player, table.name)}>{(player.weighting ?? 1).toFixed(1)}</button>)}
              {canRemoveSignups && <button type="button" className="remove-signup-player" aria-label={`Remove ${player.display_name || player.name} from signups`} title="Remove from signups" onClick={() => onRemovePlayer?.(player)}>✕</button>}
            </li>)}
          </ul> : <p className="help">{count === 0 ? event.status === "assigned" ? "No players assigned." : "No players signed up yet." : error ? "Signups unavailable." : <LoadingIndicator label="Loading signups…" />}</p>}
          {canEditSignups && <button type="button" className="add-signup-player" onClick={() => onAddPlayer?.(table.name)}>Add Player</button>}
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
