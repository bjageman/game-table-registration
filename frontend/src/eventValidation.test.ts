import { expect, it } from "vitest";
import { validateEvent, type EventDraft } from "./eventValidation";

const valid: EventDraft = {
  title: "Friday games",
  startsAt: "2090-06-14T19:00",
  duration: "24",
  tables: [{ id: 1, name: "Clocktower", capacity: "15" }],
};
it("rejects fractional or out-of-range capacities and durations", () => {
  expect(
    validateEvent({
      ...valid,
      duration: "1.5",
      tables: [{ ...valid.tables[0], capacity: "0" }],
    }),
  ).toMatchObject({
    duration: expect.stringContaining("whole number"),
    "capacity-1": expect.stringContaining("whole number"),
  });
  expect(
    validateEvent({
      ...valid,
      duration: "769",
      tables: [{ ...valid.tables[0], capacity: "1000" }],
    }),
  ).toHaveProperty("duration");
});
it("compares the signup deadline with the event time including equality", () => {
  const start = new Date(valid.startsAt).getTime();
  expect(validateEvent(valid, start - 24 * 3600000)).toHaveProperty("start");
  expect(validateEvent(valid, start - 25 * 3600000)).toEqual({});
});
it("rejects blank and duplicate names after trimming", () => {
  expect(validateEvent({ ...valid, title: "  " })).toHaveProperty("title");
  expect(
    validateEvent({
      ...valid,
      tables: [
        ...valid.tables,
        { id: 2, name: " clockTOWER ", capacity: "15" },
      ],
    }),
  ).toHaveProperty("name-2", "Table names must be unique.");
});
