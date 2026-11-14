import { parseWeightInput } from "../../../lib/weightInput";
import { matchesPlayer, type PlayerSummary } from "../../../lib/players";
import useDialog from "../../../hooks/useDialog";
import ModalHeader from "../../../components/ModalHeader";
import TableTitle from "../TableTitle";
import PlayerProfile from "../../players/PlayerProfile";
import { useEffect, useState } from "react";
import { api, errorMessage, mutationOptions, type EventRecord } from "../../../lib/api";
import LoadingIndicator from "../../../components/LoadingIndicator";
import ConfirmationDialog from "../../../components/ConfirmationDialog";
import { isBackdropClick } from "../../../lib/dialogBackdrop";
import { Plus, X } from "lucide-react";

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
  const [weightNotice, setWeightNotice] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [editingWeight, setEditingWeight] = useState<string>();
  const [weight, setWeight] = useState("");
  const [saving, setSaving] = useState(false);
  const [addingToWaitlist, setAddingToWaitlist] = useState(false);
  const [addingTable, setAddingTable] = useState<string>();
  const [playerQuery, setPlayerQuery] = useState("");
  const [availablePlayers, setAvailablePlayers] = useState<PlayerSummary[]>([]);
  const [playersLoading, setPlayersLoading] = useState(false);
  const [removing, setRemoving] = useState<{ player: SignupPlayer; willPromote: boolean; fromWaitlist?: boolean; table?: string }>();
  const [assigning, setAssigning] = useState<{ table: string; player: SignupPlayer }>();
  const addDialog = useDialog(Boolean(addingTable));
  const hasSignups = event.status === "open" || event.status === "closing" || event.status === "review" || event.status === "assigned" || Boolean(event.discord_url) || Boolean(event.is_test);
  const canEditSignups = !readOnly && !event.archived_at && (event.status === "draft" || event.status === "scheduled" || event.status === "open" || event.status === "assigned" || event.status === "review");
  const canRemoveSignups = !readOnly && (canEditSignups || event.status === "assigned");
  const normalizedQuery = playerQuery.trim().toLocaleLowerCase();
  const suggestions = normalizedQuery ? availablePlayers.filter((player) =>
    matchesPlayer(player, normalizedQuery)
      && (!(event.status === "assigned" || event.status === "review") || !rows?.some((row) => row.players.some((seated) => seated.id === player.discord_id)))
      && (!addingToWaitlist || !rows?.find((row) => row.name === addingTable)?.waitlist?.some((entry) => entry.id === player.discord_id)),
  ).slice(0, 30) : [];
  function closeAddPlayer() {
    if (saving) return;
    setAddingTable(undefined);
    setPlayerQuery("");
  }
  useEffect(() => {
    if (!addingTable) return;
    let active = true;
    api<PlayerSummary[]>("/players")
      .then((players) => { if (active) setAvailablePlayers(players); })
      .catch((failure) => { if (active && !onAccessError(failure)) setActionError(errorMessage(failure)); })
      .finally(() => { if (active) setPlayersLoading(false); });
    return () => { active = false; };
  }, [addingTable, onAccessError]);
  async function addPlayer(player: PlayerSummary) {
    if (!addingTable || saving) return;
    setSaving(true); setActionError("");
    try {
      await api(`/events/${encodeURIComponent(event.id)}/${addingToWaitlist ? "waitlisted-players" : "manager-players"}/${encodeURIComponent(player.discord_id)}`,
        { ...mutationOptions(csrf, { table: addingTable, ...(addingToWaitlist ? {} : { name: player.discord_name }) }), method: addingToWaitlist ? "POST" : "PUT" });
      const signupPlayer = { id: player.discord_id, name: player.discord_name };
      setRows((current) => {
        const value: TableSignups[] = current ?? event.tables.map((table) => ({ name: table.name, players: [] }));
        return value.map((row) => {
          if (row.name !== addingTable) return row;
          if (addingToWaitlist) return { ...row, waitlist: [...(row.waitlist ?? []), signupPlayer] };
          return !row.players.some((entry) => entry.id === signupPlayer.id)
            ? { ...row, players: [...row.players, signupPlayer] } : row;
        });
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
      await api(`/events/${encodeURIComponent(event.id)}/manager-players/${encodeURIComponent(player.id)}${event.status === "open" && removing?.table ? `?table=${encodeURIComponent(removing.table)}` : ""}`,
        { ...mutationOptions(csrf), method: "DELETE" });
      setRows((current) => current?.map((row) => ({
        ...row,
        players: event.status === "open" && removing?.table !== row.name ? row.players : row.players.filter((entry) => entry.id !== player.id),
        waitlist: row.waitlist?.filter((entry) => entry.id !== player.id),
      })));
      setRemoving(undefined);
      setAttempt((value) => value + 1);
    } catch (failure) {
      if (!onAccessError(failure)) setActionError(errorMessage(failure));
    } finally { setSaving(false); }
  }
  async function assignWaitlistedPlayer() {
    if (!assigning || saving) return;
    setSaving(true); setActionError("");
    try {
      await api(`/events/${encodeURIComponent(event.id)}/assigned-players/${encodeURIComponent(assigning.player.id)}`,
        { ...mutationOptions(csrf, { table: assigning.table }), method: "POST" });
      setAssigning(undefined);
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
          timer = setTimeout(() => void refresh(), 15000);
        }
      }
    }
    void refresh();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [event.id, event.discord_url, event.status, event.is_test, event.test_generation, hasSignups, attempt, refreshToken, onAccessError, onRefreshingChange]);
  return <>
    {selectedPlayer && <PlayerProfile key={selectedPlayer.id} player={selectedPlayer} csrf={csrf} readOnly={readOnly}
      onSaved={() => setAttempt((value) => value + 1)} onClose={() => setSelectedPlayer(undefined)} onAccessError={onAccessError} />}
    {addingTable && <dialog id={`event-add-player-dialog-${event.id}`} ref={addDialog} className="event-modal" aria-labelledby="add-player-heading"
      onCancel={(event) => { event.preventDefault(); closeAddPlayer(); }}
      onClick={(event) => { if (isBackdropClick(event)) closeAddPlayer(); }}>
      <ModalHeader>
        <h2 id="add-player-heading">Add a player to {addingTable}{addingToWaitlist ? " waitlist" : ""}</h2>
      </ModalHeader>
      {actionError && <p role="alert" className="error">{actionError}</p>}
      <div className="add-player-search">
        <label htmlFor="add-player-query">Search players</label>
        <input id="add-player-query" type="search" autoFocus autoComplete="off" placeholder="Name or Discord ID"
          role="combobox" aria-autocomplete="list" aria-expanded={suggestions.length > 0} aria-controls="add-player-suggestions"
          value={playerQuery} onChange={(change) => setPlayerQuery(change.target.value)} />
        {playersLoading ? <p><LoadingIndicator label="Loading players…" /></p> : normalizedQuery ? suggestions.length ?
          <ul id="add-player-suggestions" className="add-player-results" role="listbox" aria-label="Suggested players">
            {suggestions.map((player) => <li key={player.discord_id} role="option" aria-selected="false">
              <button id={`event-add-player-select-${player.discord_id}`} type="button" disabled={saving} onClick={() => void addPlayer(player)}>
                <strong>{player.real_name || player.discord_name}</strong>
                <span>{player.real_name ? `@${player.discord_name} · ` : ""}{player.discord_id}</span>
              </button>
            </li>)}
          </ul> : <p className="help">No known players match “{playerQuery}”.</p>
          : null}
      </div>
      <div className="form-actions"><button id="event-add-player-cancel-button" type="button" disabled={saving} onClick={closeAddPlayer}>Cancel</button></div>
    </dialog>}
    {removing && <ConfirmationDialog id={`event-remove-player-dialog-${event.id}`} title={removing.fromWaitlist ? "Remove player from waitlist?" : event.status === "assigned" ? "Remove player from table?" : "Remove player from signups?"} busy={saving} error="" onCancel={() => setRemoving(undefined)} onConfirm={() => void removePlayer(removing.player)}>
      <p>{removing.fromWaitlist ? `Remove ${removing.player.display_name || removing.player.name} from the waitlist? They will not be added to a table.` : event.status === "assigned" ? `Remove ${removing.player.display_name || removing.player.name} from their table? ${removing.willPromote ? "The next waitlisted player will be added automatically." : "No waitlisted player will be added automatically."}` : `Remove ${removing.player.display_name || removing.player.name} from ${removing.table || "this table"}’s signups? They will not be notified.`}</p>
    </ConfirmationDialog>}
    {assigning && <ConfirmationDialog id={`event-add-waitlisted-player-dialog-${event.id}`} title="Add waitlisted player?" busy={saving} error={actionError}
      onCancel={() => { setAssigning(undefined); setActionError(""); }} onConfirm={() => void assignWaitlistedPlayer()}>
      <p>Are you sure you want to add this player? It will go beyond the table limit.</p>
    </ConfirmationDialog>}
    {error && <p role="alert" className="error">
      Could not refresh signups. {rows ? "Showing the last loaded list. " : ""}{error}{" "}
      <button type="button" onClick={() => setAttempt((value) => value + 1)}>Retry signups</button>
    </p>}
    {weightNotice && <p role="status" className="notice">{weightNotice}</p>}
    {actionError && !assigning && !addingTable && <p role="alert" className="error">{actionError}</p>}
    <TableColumns event={event} rows={hasSignups ? rows : rows ?? event.tables.map((t) => ({ name: t.name, players: [] }))} error={error} onSelect={readOnly ? undefined : setSelectedPlayer}
      canEditSignups={canEditSignups} canRemoveSignups={canRemoveSignups} onAddPlayer={(table) => { setPlayersLoading(true); setActionError(""); setAddingToWaitlist(false); setAddingTable(table); }}
      onAddToWaitlist={(table) => { setPlayersLoading(true); setActionError(""); setAddingToWaitlist(true); setAddingTable(table); }} onRemovePlayer={(player, willPromote, fromWaitlist, table) => setRemoving({ player, willPromote, fromWaitlist, table })}
      onAssignWaitlisted={!readOnly && (event.status === "assigned" || event.status === "review") ? (player, table) => { setActionError(""); setAssigning({ player, table }); } : undefined}
      editingWeight={editingWeight} weight={weight} saving={saving} readOnly={readOnly} onWeightChange={setWeight}
      onEditWeight={(player, table) => { setEditingWeight(`${player.id}:${table}`); setWeight(String(player.weighting ?? 5)); }}
      onCancelWeight={() => setEditingWeight(undefined)}
      onSaveWeight={(player) => {
        const parsed = parseWeightInput(weight);
        if (!parsed) { setActionError("Enter a valid weight."); return; }
        const { value, notice } = parsed;
        setActionError("");
        setWeight(String(value));
        setWeightNotice(notice);
        if (value === (player.weighting ?? 5)) setEditingWeight(undefined);
        else void saveSetting(player, { weighting: value });
      }}
      onToggleGuarantee={(player, table) => void saveSetting(player, { guaranteed_table: player.guaranteed_table === table ? null : table })} />
  </>;
}

export function TableColumns({ event, rows, error = "", onSelect, editingWeight, weight = "", saving = false, readOnly = false, onWeightChange, onEditWeight, onCancelWeight, onSaveWeight, onToggleGuarantee, canEditSignups = false, canRemoveSignups = false, onAddPlayer, onAddToWaitlist, onRemovePlayer, onAssignWaitlisted }: {
  event: Pick<EventRecord, "id" | "tables" | "status" | "scheduled_publish_at">;
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
  onAddToWaitlist?: (table: string) => void;
  onRemovePlayer?: (player: SignupPlayer, willPromote: boolean, fromWaitlist?: boolean, table?: string) => void;
  onAssignWaitlisted?: (player: SignupPlayer, table: string) => void;
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
    <ul id={`event-tables-${event.id}`} className="event-tables" aria-label="Tables">
      {event.tables.map((table, tableIndex) => {
        const tableId = `event-${event.id}-table-${tableIndex + 1}`;
        const row = rows?.find((row) => row.name === table.name);
        const players = row?.players;
        const count = rows ? players?.length : undefined;
        const sort = sorts[table.name];
        const sortedPlayers = players && sort && event.status === "open" ? [...players].sort((a, b) => {
          const difference = sort.column === "guarantee"
            ? Number(isGuaranteedAtTable(b, table.name)) - Number(isGuaranteedAtTable(a, table.name))
            : sort.column === "weight"
              ? (a.weighting ?? 5) - (b.weighting ?? 5)
              : (a.display_name || a.name).localeCompare(b.display_name || b.name, undefined, { sensitivity: "base" });
          return sort.descending ? -difference : difference;
        }) : players;
        const header = (column: SortColumn, label: string, accessibleLabel: string) => <button id={`${tableId}-sort-${column}`} type="button" className="table-player-sort"
          aria-label={`Sort ${table.name} by ${accessibleLabel}${sort?.column === column ? `, ${sort.descending ? "descending" : "ascending"}` : ""}`}
          aria-pressed={sort?.column === column} onClick={() => sortTable(table.name, column)}>
          {label}{sort?.column === column && <span aria-hidden="true">{sort.descending ? "▼" : "▲"}</span>}
        </button>;
        return <li id={tableId} key={table.name} className="event-table">
          <div className="table-heading">
            <TableTitle>{table.name}</TableTitle>
            <span className="table-player-count" aria-label={`${count ?? "Unknown"} ${(event.status === "assigned" || event.status === "review") ? "assigned players" : "signups"} for ${table.capacity} seats`}>
              {count ?? "—"}/{table.capacity}
            </span>
          </div>
          {event.status === "open" && <div className={`table-player-header${readOnly ? " read-only" : ""}`}>
            {!readOnly && header("guarantee", "⭐", "guarantee")}{readOnly ? <span>Player</span> : header("player", "Player", "player")}{readOnly ? <span>Wt</span> : header("weight", "Wt", "weight")}
          </div>}
          {players?.length ? <ul className="table-players">
            {sortedPlayers?.map((player) => <li key={player.id} className={event.status === "open" ? `table-player-row${readOnly ? " read-only" : ""}` : "table-assigned-player"}>
              {event.status === "open" && !readOnly && <button id={`${tableId}-player-guarantee-${player.id}`} type="button" className="player-guarantee" disabled={saving} aria-pressed={player.guaranteed_table === table.name}
                aria-label={`${player.guaranteed_table === table.name ? "Remove" : "Guarantee"} ${player.display_name || player.name} at ${table.name}`}
                title={player.guaranteed_table === table.name ? "Remove table guarantee" : player.guaranteed_seat && !player.guaranteed_table ? "Profile guarantees a seat at one selected table; click to guarantee this table" : "Guarantee this table"}
                onClick={() => onToggleGuarantee?.(player, table.name)}>{isGuaranteedAtTable(player, table.name) ? "⭐" : "⚪"}</button>}
              {onSelect ? <button id={`${tableId}-player-profile-${player.id}`} type="button" className="player-name" aria-haspopup="dialog"
                title={player.display_name || player.name} aria-label={player.display_name || player.name}
                onClick={() => onSelect(player)}>{event.status === "open" ? <>{(player.display_name || player.name).slice(0, 26)}{(player.display_name || player.name).length > 26 ? "…" : ""}</> : player.display_name || player.name}</button> : event.status === "open" ? (player.display_name || player.name).slice(0, 26) : player.display_name || player.name}
              {event.status === "open" && (readOnly ? <span className="player-weight">{(player.weighting ?? 5).toFixed(1)}</span> : editingWeight === `${player.id}:${table.name}` ? <form className="player-weight-editor" onSubmit={(submit) => { submit.preventDefault(); onSaveWeight?.(player); }}>
                <input id={`${tableId}-player-weight-input-${player.id}`} type="text" inputMode="decimal" aria-label={`Weight for ${player.display_name || player.name}`} value={weight} onChange={(change) => onWeightChange?.(change.target.value)}
                  onBlur={() => onSaveWeight?.(player)} onKeyDown={(key) => { if (key.key === "Escape") { key.preventDefault(); onCancelWeight?.(); } }} disabled={saving} autoFocus />
              </form> : <button id={`${tableId}-player-weight-${player.id}`} type="button" className={`player-weight ${(player.weighting ?? 5) < 5 ? "low" : (player.weighting ?? 5) > 5 ? "high" : ""}`}
                title="Edit event weight" aria-label={`Edit weight for ${player.display_name || player.name}: ${(player.weighting ?? 5).toFixed(1)}`} disabled={saving}
                onClick={() => onEditWeight?.(player, table.name)}>{(player.weighting ?? 5).toFixed(1)}</button>)}
              {canRemoveSignups && <button id={`${tableId}-player-remove-${player.id}`} type="button" className="remove-signup-player" aria-label={`Remove ${player.display_name || player.name} from ${event.status === "assigned" ? "table" : "signups"}`} title={event.status === "assigned" ? "Remove from table" : "Remove from signups"} onClick={() => onRemovePlayer?.(player, event.status === "assigned" && Boolean(row?.waitlist?.length) && (players?.length ?? 0) <= table.capacity, false, table.name)}>✕</button>}
            </li>)}
          </ul> : <p className="help">{count === 0 ? (event.status === "assigned" || event.status === "review") ? "No players assigned." : "No players signed up yet." : error ? "Signups unavailable." : <LoadingIndicator label="Loading signups…" />}</p>}
          {canEditSignups && event.status !== "scheduled" && !(event.status === "draft" && event.scheduled_publish_at != null) && <button id={`${tableId}-add-player`} type="button" className="add-signup-player" onClick={() => onAddPlayer?.(table.name)}>Add Player</button>}
          {(event.status === "assigned" || event.status === "review") && row && <div className="table-waitlist">
            <h4>Waitlist</h4>
            {row.waitlist?.length ? <ul aria-label={`Waitlist for ${table.name}`}>{row.waitlist.map((player) => <li key={player.id}>
              {onAssignWaitlisted && <button id={`${tableId}-waitlist-add-${player.id}`} type="button" className="add-waitlisted-player" disabled={saving}
                aria-label={`Add ${player.display_name || player.name} to ${table.name}`} title="Add to table"
                onClick={() => onAssignWaitlisted(player, table.name)}><Plus size={16} aria-hidden="true" /></button>}
              {onSelect ? <button id={`${tableId}-waitlist-profile-${player.id}`} type="button" className="player-name" aria-haspopup="dialog" onClick={() => onSelect(player)}>{player.display_name || player.name}</button> : player.display_name || player.name}
              {canRemoveSignups && <button id={`${tableId}-waitlist-remove-${player.id}`} type="button" className="remove-signup-player" disabled={saving}
                aria-label={`Remove ${player.display_name || player.name} from waitlist`} title="Remove from waitlist"
                onClick={() => onRemovePlayer?.(player, false, true)}><X size={16} aria-hidden="true" /></button>}
            </li>)}</ul> : <p className="help">No players waiting.</p>}
            {canEditSignups && <button id={`${tableId}-add-waitlist-player`} type="button" className="add-signup-player" disabled={saving}
              onClick={() => onAddToWaitlist?.(table.name)}>Add Player to Waitlist</button>}
          </div>}
        </li>;
      })}
    </ul>
  );
}
