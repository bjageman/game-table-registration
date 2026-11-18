import { useState } from "react";

interface Entry { arrived: boolean; notes: string }
type Entries = Record<string, Entry>;

function loadEntries(key: string): Entries {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(key) ?? "{}");
    if (!saved || typeof saved !== "object" || Array.isArray(saved)) return {};
    return Object.fromEntries(Object.entries(saved).filter(([, entry]) =>
      entry && typeof entry === "object" && typeof entry.arrived === "boolean" && typeof entry.notes === "string",
    ));
  } catch { return {}; }
}

export function usePublicChecklist(token: string) {
  const key = `public-event-checklist:${token}`;
  const [entries, setEntries] = useState(() => loadEntries(key));
  const [saveError, setSaveError] = useState("");

  function update(id: string, change: Partial<Entry>) {
    const next = { ...entries, [id]: { ...(entries[id] ?? { arrived: false, notes: "" }), ...change } };
    setEntries(next);
    try {
      localStorage.setItem(key, JSON.stringify(next));
      setSaveError("");
    } catch {
      setSaveError("Changes could not be saved in this browser and will be lost when you leave this page.");
    }
  }

  return { entries, update, saveError };
}

export function ChecklistPlayer({ player, entry, onChange, controlId }: {
  player: { id: string; name: string };
  entry?: Entry;
  onChange: (change: Partial<Entry>) => void;
  controlId: string;
}) {
  return <li>
    <div className="public-checklist-player">
      <label className="public-checklist-name" htmlFor={`${controlId}-arrived`}>
        <input id={`${controlId}-arrived`} type="checkbox" checked={entry?.arrived ?? false}
          aria-label={`Mark ${player.name} as arrived`} onChange={(event) => onChange({ arrived: event.target.checked })} />
        <span className={entry?.arrived ? "public-player-arrived" : undefined}>{player.name}</span>
      </label>
      <input id={`${controlId}-notes`} className="public-player-notes" type="text" placeholder="Notes"
        aria-label={`Notes for ${player.name}`} value={entry?.notes ?? ""}
        onChange={(event) => onChange({ notes: event.target.value })} />
    </div>
  </li>;
}
