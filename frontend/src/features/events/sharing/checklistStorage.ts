export interface Entry { arrived: boolean }
export type Entries = Record<string, Entry>;
export interface ServerChecklist { revision: number; entries: Record<string, boolean> }

export function loadEntries(token: string): Entries {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(`public-event-checklist:${token}`) ?? "{}");
    if (!saved || typeof saved !== "object" || Array.isArray(saved)) return {};
    return Object.fromEntries(Object.entries(saved).filter(([, entry]) =>
      entry && typeof entry === "object" && typeof entry.arrived === "boolean",
    ));
  } catch { return {}; }
}

export function loadSync(token: string) {
  try { return localStorage.getItem(`public-event-checklist-sync:${token}`) !== "false"; }
  catch { return true; }
}

export function fromServer(server: ServerChecklist): Entries {
  return Object.fromEntries(Object.entries(server.entries).map(([id, arrived]) => [id, { arrived }]));
}

export function differs(local: Entries, server: ServerChecklist) {
  return Object.entries(server.entries).some(([id, arrived]) => Boolean(local[id]?.arrived) !== arrived);
}
