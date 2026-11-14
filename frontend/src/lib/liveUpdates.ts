/** One invalidation stream per URL, shared by all mounted consumers. */
type Refresh = () => void;
const connections = new Map<string, ReturnType<typeof connection>>();

function connection(url: string) {
  const listeners = new Set<Refresh>();
  let source: EventSource | undefined;
  let connected = false;
  let debounce: ReturnType<typeof setTimeout> | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;

  function refresh() {
    if (!document.hidden) listeners.forEach((listener) => listener());
  }
  function schedule() {
    clearTimeout(timer);
    if (!document.hidden) timer = setTimeout(() => {
      refresh();
      schedule();
    }, connected ? 15000 : 2000);
  }
  function changed() {
    if (debounce !== undefined) return;
    debounce = setTimeout(() => { debounce = undefined; refresh(); }, 150);
  }
  function disconnect() {
    source?.close();
    source = undefined;
    connected = false;
    clearTimeout(timer);
    clearTimeout(debounce);
    debounce = undefined;
  }
  function connect() {
    if (document.hidden) return;
    if (typeof EventSource !== "undefined") {
      source = new EventSource(url);
      source.onopen = () => { connected = true; changed(); schedule(); };
      source.onerror = () => { connected = false; schedule(); };
      source.addEventListener("change", changed);
      source.addEventListener("access-revoked", () => {
        disconnect();
        refresh(); // Normal API requests handle expired sessions/revoked shares.
        schedule();
      });
    }
    schedule();
  }
  function visibility() {
    disconnect();
    if (!document.hidden) { refresh(); connect(); }
  }
  return {
    subscribe(listener: Refresh) {
      listeners.add(listener);
      if (listeners.size === 1) {
        document.addEventListener("visibilitychange", visibility);
        connect();
      }
      return () => {
        if (!listeners.delete(listener)) return;
        if (!listeners.size) {
          disconnect();
          document.removeEventListener("visibilitychange", visibility);
          connections.delete(url);
        }
      };
    },
  };
}

/** Callers perform their initial load and prevent overlapping requests. */
export function subscribeLiveUpdates(refresh: Refresh, url = "/api/live") {
  let shared = connections.get(url);
  if (!shared) { shared = connection(url); connections.set(url, shared); }
  return shared.subscribe(refresh);
}
