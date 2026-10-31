import type { EventRecord } from "./api";

const placeholderPlayers = ["Mary", "Dan", "Shirley", "Carl"];

export default function EventTables({ event }: { event: EventRecord }) {
  return (
    <ul className="event-tables" aria-label="Tables">
      {event.tables.map((table) => (
        <li key={table.name} className="event-table">
          <h4>{table.name} – {table.capacity} seats</h4>
          <ul className="table-players">
            {placeholderPlayers.map((name) => <li key={name}>{name}</li>)}
          </ul>
        </li>
      ))}
    </ul>
  );
}
