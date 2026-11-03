import { useEffect, useState } from "react";
import { ChevronDown, ChevronUp, Star } from "lucide-react";
import PlayerProfile from "./PlayerProfile";
import { api, errorMessage, type ModeratorSession } from "./api";
import { FormField } from "./FormFields";
import LoadingIndicator from "./LoadingIndicator";

interface Player { discord_id: string; discord_name: string; real_name: string; weighting: number; guaranteed_seat: boolean; is_test: boolean; }
type SortKey = "guaranteed_seat" | "discord_name" | "real_name" | "weighting" | "is_test";
type SortOrder = { key: SortKey; direction: "asc" | "desc" };
const sortHeaders: { key: SortKey; label: string }[] = [
  { key: "guaranteed_seat", label: "Priority" },
  { key: "discord_name", label: "Username" },
  { key: "real_name", label: "Display Name" },
  { key: "weighting", label: "Weight" },
  { key: "is_test", label: "Test Label" },
];
const nameOrder = new Intl.Collator(undefined, { sensitivity: "base", numeric: true });

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
  const [sort, setSort] = useState<SortOrder>({ key: "discord_name", direction: "asc" });

  useEffect(() => {
    const controller = new AbortController();
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
  const sorted = [...visible].sort((left, right) => {
    const leftValue = left[sort.key];
    const rightValue = right[sort.key];
    let result = typeof leftValue === "number" && typeof rightValue === "number"
      ? leftValue - rightValue
      : typeof leftValue === "boolean" && typeof rightValue === "boolean"
        ? Number(leftValue) - Number(rightValue)
        : nameOrder.compare(String(leftValue), String(rightValue));
    if (result === 0) result = nameOrder.compare(left.discord_id, right.discord_id);
    return sort.direction === "asc" ? result : -result;
  });

  function changeSort(key: SortKey) {
    setSort((current) => current.key === key
      ? { key, direction: current.direction === "asc" ? "desc" : "asc" }
      : { key, direction: "asc" });
  }

  return <section className="panel" aria-labelledby="player-lookup-heading">
    <div className="section-heading"><h2 id="player-lookup-heading">User Lookup</h2></div>
    <FormField type="search" label="Search players" placeholder="Search by name or Discord ID"
      value={query} onChange={(event) => setQuery(event.target.value)} />
    {loading && <p><LoadingIndicator label="Loading players…" /></p>}
    {error && <p role="alert" className="error">Could not load players. {error} <button type="button" onClick={() => { setLoading(true); setAttempt((value) => value + 1); }}>Retry</button></p>}
    {!loading && !error && <>
      <p>{visible.length} {visible.length === 1 ? "player" : "players"}</p>
      {visible.length ? <div className="player-lookup-table">
        <div className="player-lookup-columns">{sortHeaders.map(({ key, label }) => <button key={key}
          type="button" className="player-lookup-sort" aria-pressed={sort.key === key}
          aria-label={`Sort by ${label}${sort.key === key ? `, currently ${sort.direction === "asc" ? "ascending" : "descending"}` : ""}`}
          onClick={() => changeSort(key)}>
          {label}{sort.key === key && (sort.direction === "asc" ? <ChevronUp size={16} aria-hidden="true" /> : <ChevronDown size={16} aria-hidden="true" />)}
        </button>)}</div>
        <ul className="player-lookup-list">{sorted.map((player) => <li key={player.discord_id}>
        <button type="button" className="player-lookup-item" onClick={() => setSelected(player)}>
          <span className="player-lookup-star">{player.guaranteed_seat && <Star size={18} fill="currentColor" aria-label="Always guaranteed" />}</span>
          <span className="player-lookup-username">{player.discord_name}</span>
          <span className="player-lookup-display-name">{player.real_name || "—"}</span>
          <span className="player-lookup-weight" aria-label={`${player.weighting.toFixed(1)} weighting`}>{player.weighting.toFixed(1)}</span>
          <span className="player-lookup-test">{player.is_test && <span className="badge">Test User</span>}</span>
        </button>
      </li>)}</ul>
      </div> : <p>{players.length ? "No players match your search." : "No players have signed up yet."}</p>}
    </>}
    {selected && <PlayerProfile key={selected.discord_id} player={{ id: selected.discord_id, name: selected.discord_name }}
      csrf={session.csrf} onClose={() => setSelected(undefined)} onAccessError={onAccessError}
      onSaved={() => setAttempt((value) => value + 1)} />}
  </section>;
}
