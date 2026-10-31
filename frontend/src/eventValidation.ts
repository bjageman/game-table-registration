export interface TableDraft {
  id: number;
  name: string;
  capacity: string;
}
export interface EventDraft {
  title: string;
  startsAt: string;
  duration: string;
  tables: TableDraft[];
}

function localMinute(date: Date): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function validateEvent(
  draft: EventDraft,
  now = Date.now(),
): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!draft.title.trim() || draft.title.trim().length > 100)
    errors.title = "Enter an event title of 1–100 characters.";
  const hours = Number(draft.duration);
  if (!Number.isInteger(hours) || hours < 1 || hours > 768)
    errors.duration =
      "Signup duration must be a whole number from 1 to 768 hours.";
  const start = new Date(draft.startsAt);
  if (Number.isNaN(start.getTime()) || localMinute(start) !== draft.startsAt) {
    errors.start =
      "Enter a valid local date and time. This time may not exist because the clocks change.";
  } else {
    // A different offset can produce the same wall time when clocks go back.
    const offsets = [-86400000, 86400000].map((delta) =>
      new Date(start.getTime() + delta).getTimezoneOffset(),
    );
    if (
      offsets.some(
        (offset) =>
          offset !== start.getTimezoneOffset() &&
          localMinute(
            new Date(
              start.getTime() + (offset - start.getTimezoneOffset()) * 60000,
            ),
          ) === draft.startsAt,
      )
    ) {
      errors.start =
        "This local time occurs twice when the clocks change. Choose an unambiguous time.";
    } else if (start.getTime() <= now + hours * 3600000) {
      errors.start =
        "The event must start after the signup window ends. Choose a later time or a shorter signup duration.";
    }
  }
  const names = new Set<string>();
  for (const table of draft.tables) {
    const name = table.name.trim();
    if (!name || name.length > 35)
      errors[`name-${table.id}`] = "Enter a table name of 1–35 characters.";
    else if (names.has(name.toLowerCase()))
      errors[`name-${table.id}`] = "Table names must be unique.";
    names.add(name.toLowerCase());
    const capacity = Number(table.capacity);
    if (!Number.isInteger(capacity) || capacity < 1 || capacity > 999)
      errors[`capacity-${table.id}`] =
        "Capacity must be a whole number from 1 to 999.";
  }
  return errors;
}
