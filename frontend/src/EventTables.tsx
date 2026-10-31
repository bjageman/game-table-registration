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
          <div className="table-heading">
            <h3>{table.name}</h3>
            <span className="table-player-count" aria-label={`${table.capacity} of ${table.capacity} seats filled`}>
              {table.capacity}/{table.capacity}
            </span>
          </div>
          <ul className="table-players">
            {Array.from({ length: table.capacity }, (_, index) => (
              <li key={index}>
                {placeholderPlayers[index] ?? `Player ${index + 1}`}
              </li>
            ))}
          </ul>
          <div className="table-waitlist">
            <h5>Waitlist</h5>
            <ol>
              <li>Pat</li>
              <li>Drew</li>
              <li>Lee</li>
            </ol>
          </div>
        </li>
      ))}
    </ul>
  );
}
