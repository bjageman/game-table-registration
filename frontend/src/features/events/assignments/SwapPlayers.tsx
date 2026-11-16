import { useState } from "react";
import useDialog from "../../../hooks/useDialog";
import ModalHeader from "../../../components/ModalHeader";
import { api, errorMessage, mutationOptions } from "../../../lib/api";
import { isBackdropClick } from "../../../lib/dialogBackdrop";
import type { SignupPlayer, TableSignups } from "./EventTables";

export interface Placement { player: SignupPlayer; table: string; waitlist: boolean }

export default function SwapPlayers({ eventId, csrf, source, rows, onClose, onSaved, onAccessError }: {
  eventId: string; csrf: string; source: Placement; rows: TableSignups[];
  onClose: () => void; onSaved: () => void; onAccessError: (error: unknown) => boolean;
}) {
  const dialog = useDialog();
  const [query, setQuery] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const candidates = rows
    .flatMap((row) => [
      ...row.players.map((player) => ({ player, table: row.name, waitlist: false })),
      ...(row.waitlist ?? []).map((player) => ({ player, table: row.name, waitlist: true })),
    ])
    .filter(({ player, table, waitlist }) => player.id !== source.player.id
      && (source.waitlist || waitlist || table !== source.table)
      && (table === source.table || !rows.find((row) => row.name === source.table)?.players.some((p) => p.id === player.id))
      && `${player.name} ${player.display_name ?? ""} ${player.id}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  async function swap(target: Placement) {
    if (saving) return;
    setSaving(true); setError("");
    try {
      await api(`/events/${encodeURIComponent(eventId)}/swap-players`, mutationOptions(csrf, {
        player_id: source.player.id, table: source.table, waitlist: source.waitlist,
        other_player_id: target.player.id, other_table: target.table, other_waitlist: target.waitlist,
      }));
      onSaved();
    } catch (failure) { if (!onAccessError(failure)) setError(errorMessage(failure)); }
    finally { setSaving(false); }
  }
  function close() { if (!saving) onClose(); }
  return <dialog ref={dialog} className="event-modal" aria-labelledby="swap-player-heading"
    onCancel={(event) => { event.preventDefault(); close(); }} onClick={(event) => { if (isBackdropClick(event)) close(); }}>
    <ModalHeader><h2 id="swap-player-heading">Swap {source.player.display_name || source.player.name}</h2></ModalHeader>
    <p>Select a player to exchange placements. Other waitlisted players will stay in place.</p>
    {error && <p role="alert" className="error">{error}</p>}
    <div className="add-player-search">
      <label htmlFor="swap-player-query">Search players to swap</label>
      <input id="swap-player-query" type="search" autoFocus value={query} onChange={(change) => setQuery(change.target.value)} />
      <ul className="add-player-results" aria-label="Swap candidates">
        {candidates.map((target) => <li key={`${target.table}:${target.waitlist}:${target.player.id}`}>
          <button type="button" disabled={saving} onClick={() => void swap(target)}>
            <strong>{target.player.display_name || target.player.name}</strong><span>{target.table}{target.waitlist ? " · Waitlist" : " · Seated"}</span>
          </button>
        </li>)}
      </ul>
      {!candidates.length && <p>No eligible players found.</p>}
    </div>
    <div className="form-actions"><button type="button" disabled={saving} onClick={close}>Cancel</button></div>
  </dialog>;
}
