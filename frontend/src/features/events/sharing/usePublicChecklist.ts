import { useEffect, useRef, useState } from "react";
import { api, ApiError, errorMessage } from "../../../lib/api";
import { pollWhileVisible } from "../../../lib/visiblePolling";
import { differs, fromServer, loadEntries, loadSync, type Entries, type Entry, type ServerChecklist } from "./checklistStorage";

type Mode = "local" | "connecting" | "synced" | "conflict";

export function usePublicChecklist(token: string) {
  const path = `/public/events/${encodeURIComponent(token)}/checklist`;
  const [entries, setEntries] = useState(() => loadEntries(token));
  const current = useRef(entries);
  const [mode, setMode] = useState<Mode>(() => loadSync(token) ? "connecting" : "local");
  const modeRef = useRef(mode);
  const [busy, setBusy] = useState(false);
  const saving = useRef(false);
  const [conflict, setConflict] = useState<ServerChecklist>();
  const [saveError, setSaveError] = useState("");
  const [syncError, setSyncError] = useState("");
  const generation = useRef(0);

  function transition(next: Mode) {
    modeRef.current = next;
    setMode(next);
    try { localStorage.setItem(`public-event-checklist-sync:${token}`, String(next !== "local")); }
    catch { setSaveError("Browser storage is unavailable. Your sync preference will not be remembered."); }
  }

  function remember(next: Entries) {
    current.current = next;
    setEntries(next);
    try {
      localStorage.setItem(`public-event-checklist:${token}`, JSON.stringify(next));
      setSaveError("");
    } catch {
      setSaveError("Changes could not be saved in this browser and will be lost when you leave this page.");
    }
  }

  function accept(server: ServerChecklist) {
    remember(fromServer(server));
    setConflict(undefined);
    setSyncError("");
    transition("synced");
  }

  // On initial load the server is authoritative; existing browser data is used
  // only when this link's sync preference was explicitly turned off.
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    async function refresh() {
      if (saving.current || !["synced", "connecting"].includes(modeRef.current)) return;
      const started = generation.current;
      try {
        const server = await api<ServerChecklist>(path, { cache: "no-store", signal: controller.signal });
        if (active && started === generation.current && !saving.current) accept(server);
      } catch (failure) {
        if (active && started === generation.current) {
          setSyncError(`Could not refresh the server checklist. ${errorMessage(failure)}`);
          if (modeRef.current === "connecting") transition("local");
        }
      }
    }
    const stop = pollWhileVisible(refresh);
    function invalidatePending() { generation.current++; }
    return () => { active = false; invalidatePending(); stop(); controller.abort(); };
    // The public page is keyed by share token; refs let polling see current edits.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path]);

  async function setSync(enabled: boolean) {
    if (saving.current) return;
    const started = ++generation.current;
    setSyncError("");
    if (!enabled) { setConflict(undefined); transition("local"); return; }
    transition("connecting");
    saving.current = true; setBusy(true);
    try {
      const server = await api<ServerChecklist>(path, { cache: "no-store" });
      if (started !== generation.current) return;
      if (differs(current.current, server)) { setConflict(server); transition("conflict"); }
      else accept(server);
    } catch (failure) {
      if (started === generation.current) {
        setSyncError(`Could not enable sync. ${errorMessage(failure)}`);
        transition("local");
      }
    } finally { saving.current = false; setBusy(false); }
  }

  async function update(id: string, change: Partial<Entry>) {
    if (saving.current || !["local", "synced"].includes(modeRef.current)) return;
    const next = { ...current.current, [id]: { ...(current.current[id] ?? { arrived: false }), ...change } };
    remember(next);
    if (modeRef.current === "local") return;
    const started = ++generation.current;
    saving.current = true; setBusy(true); setSyncError("");
    try {
      const server = await api<ServerChecklist>(path, { method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ player_id: id, arrived: next[id].arrived }) });
      if (started === generation.current) accept(server);
    } catch (failure) {
      if (started === generation.current) {
        transition("local");
        setSyncError(`Sync was turned off because this change could not be confirmed on the server. Your browser version was kept. ${errorMessage(failure)}`);
      }
    } finally { saving.current = false; setBusy(false); }
  }

  async function resolve(side: "browser" | "server") {
    if (!conflict || saving.current) return;
    const started = ++generation.current;
    saving.current = true; setBusy(true); setSyncError("");
    try {
      const server = side === "server"
        ? await api<ServerChecklist>(path, { cache: "no-store" })
        : await api<ServerChecklist>(path, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
          revision: conflict.revision,
          entries: Object.fromEntries(Object.keys(conflict.entries).map(id => [id, Boolean(current.current[id]?.arrived)])),
        }) });
      if (started === generation.current) accept(server);
    } catch (failure) {
      if (started !== generation.current) return;
      if (failure instanceof ApiError && (failure.status === 409 || failure.status === 422)) {
        try {
          const latest = await api<ServerChecklist>(path, { cache: "no-store" });
          if (started === generation.current) {
            setConflict(latest);
            setSyncError("The server checklist changed. Choose again using its latest version.");
          }
        } catch (refreshFailure) { setSyncError(errorMessage(refreshFailure)); }
      } else setSyncError(errorMessage(failure));
    } finally { saving.current = false; setBusy(false); }
  }

  return { entries, update, saveError, syncError, busy, conflict, resolve, setSync,
    syncing: mode !== "local", disabled: busy || mode === "connecting" || mode === "conflict" };
}
