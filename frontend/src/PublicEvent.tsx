import { useEffect, useState } from "react";
import { api, errorMessage } from "./api";

interface SharedEvent {
  title: string; description: string; location: string; starts_at: number; archived: boolean;
  tables: { name: string; capacity: number; players: { name: string }[]; waitlist: { name: string }[] }[];
}

export default function PublicEvent({ token }: { token: string }) {
  const [event, setEvent] = useState<SharedEvent | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    let inFlight = false;
    async function refresh() {
      if (inFlight) return;
      inFlight = true;
      try {
        const result = await api<SharedEvent>(`/public/events/${encodeURIComponent(token)}`, { signal: controller.signal, cache: "no-store" });
        if (!controller.signal.aborted) { setEvent(result); setError(""); }
      } catch (failure) { if (!controller.signal.aborted) setError(errorMessage(failure)); }
      finally { inFlight = false; }
    }
    void refresh();
    const timer = window.setInterval(() => void refresh(), 15000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [token]);
  useEffect(() => { if (event) document.title = `${event.title} — Table assignments`; }, [event]);
  return <main className="public-event-page">
    {error && <p role="alert" className="error">{error}</p>}
    {!event && !error && <p role="status">Loading table assignments…</p>}
    {event && <>
      <header><h1>{event.title}</h1><p>Table assignments{event.archived ? " · Archived" : " · Updates automatically"}</p></header>
      <dl className="event-details">
        <div><dt>Event starts</dt><dd><time dateTime={new Date(event.starts_at * 1000).toISOString()}>{new Date(event.starts_at * 1000).toLocaleString()}</time></dd></div>
        {event.location && <div><dt>Location</dt><dd>{event.location}</dd></div>}
      </dl>
      {event.description && <p className="public-event-description">{event.description}</p>}
      <ul className="event-tables" aria-label="Table assignments">{event.tables.map((table) => <li className="event-table" key={table.name}>
        <div className="table-heading"><h2>{table.name}</h2><span className="table-player-count">{table.players.length}/{table.capacity}</span></div>
        {table.players.length ? <ol>{table.players.map((player, index) => <li key={index}>{player.name}</li>)}</ol> : <p>No seated players.</p>}
        {table.waitlist.length > 0 && <><h3>Waitlisted ({table.waitlist.length})</h3><ol>{table.waitlist.map((player, index) => <li key={index}>{player.name}</li>)}</ol></>}
      </li>)}</ul>
    </>}
  </main>;
}
