import { useEffect, useState } from "react";
import PlayerProfile from "./PlayerProfile";
import { api, errorMessage, type ModeratorSession } from "./api";
import { FormField } from "./FormFields";
import LoadingIndicator from "./LoadingIndicator";

interface Player { discord_id: string; discord_name: string; real_name: string; is_test: boolean; }

export default function PlayerLookup({ session, onAccessError }: {
  session: ModeratorSession;
  onAccessError: (error: unknown) => boolean;
}) {
  const [players, setPlayers] = useState<Player[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [selected, setSelected] = useState<Player>();

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    api<Player[]>("/players", { signal: controller.signal })
      .then((value) => { if (!controller.signal.aborted) { setPlayers(value); setError(""); } })
      .catch((failure) => { if (!controller.signal.aborted && !onAccessError(failure)) setError(errorMessage(failure)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [attempt, onAccessError]);

  const normalized = query.trim().toLocaleLowerCase();
  const visible = players.filter((player) =>
    `${player.discord_name} ${player.real_name} ${player.discord_id}`
      .toLocaleLowerCase().includes(normalized),
  );

  return <section className="panel" aria-labelledby="player-lookup-heading">
    <div className="section-heading"><h2 id="player-lookup-heading">User Lookup</h2></div>
    <FormField type="search" label="Search players" placeholder="Search by name or Discord ID"
      value={query} onChange={(event) => setQuery(event.target.value)} />
    {loading && <p><LoadingIndicator label="Loading players…" /></p>}
    {error && <p role="alert" className="error">Could not load players. {error} <button type="button" onClick={() => setAttempt((value) => value + 1)}>Retry</button></p>}
    {!loading && !error && <>
      <p>{visible.length} {visible.length === 1 ? "player" : "players"}</p>
      {visible.length ? <ul className="player-lookup-list">{visible.map((player) => <li key={player.discord_id}>
        <button type="button" className="player-lookup-item" onClick={() => setSelected(player)}>
          <span><strong>{player.real_name || player.discord_name}</strong>{player.real_name && <small>{player.discord_name}</small>}</span>
          {player.is_test && <span className="badge">Test User</span>}
        </button>
      </li>)}</ul> : <p>{players.length ? "No players match your search." : "No players have signed up yet."}</p>}
    </>}
    {selected && <PlayerProfile key={selected.discord_id} player={{ id: selected.discord_id, name: selected.discord_name }}
      csrf={session.csrf} onClose={() => setSelected(undefined)} onAccessError={onAccessError}
      onSaved={() => setAttempt((value) => value + 1)} />}
  </section>;
}
