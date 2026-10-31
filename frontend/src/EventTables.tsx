import type { EventRecord } from "./api";

const placeholderPlayers = [
  "Mary", "Dan", "Shirley", "Carl", "Alex", "Sam", "Jordan", "Taylor",
  "Morgan", "Jamie", "Casey", "Riley", "Avery", "Quinn", "Robin",
];

export default function EventTables({ event }: { event: EventRecord }) {
  return (
    <ul className="event-tables" aria-label="Tables">
      {event.tables.map((table) => (
        <li key={table.name} className="event-table">
          <h4>{table.name} – {table.capacity} seats</h4>
          <ul className="table-players">
            {Array.from({ length: table.capacity }, (_, index) => (
              <li key={index}>
                {placeholderPlayers[index] ?? `Player ${index + 1}`}
              </li>
            ))}
          </ul>
        </li>
      ))}
    </ul>
  );
}
