import { expect, it } from "vitest";
import { formatTimestamp, resolveLocalTime } from "./timezone";

it("converts wall times in a chosen timezone independently of the browser", () => {
  expect(resolveLocalTime("2090-06-14T19:00", "America/New_York").date?.toISOString()).toBe("2090-06-14T23:00:00.000Z");
  expect(resolveLocalTime("2090-06-14T19:00", "Asia/Kolkata").date?.toISOString()).toBe("2090-06-14T13:30:00.000Z");
  expect(resolveLocalTime("2090-06-14T19:00", "UTC").date?.toISOString()).toBe("2090-06-14T19:00:00.000Z");
});

it("rejects nonexistent, repeated, and invalid dates", () => {
  expect(resolveLocalTime("2027-03-14T02:30", "America/New_York")).toEqual({ date: null, ambiguous: false });
  expect(resolveLocalTime("2027-11-07T01:30", "America/New_York")).toEqual({ date: null, ambiguous: true });
  expect(resolveLocalTime("2027-02-30T19:00", "UTC").date).toBeNull();
  expect(resolveLocalTime("", "UTC").date).toBeNull();
});

it("formats timestamps in the selected timezone without abbreviations", () => {
  const timestamp = Date.parse("2027-01-15T19:00:00Z") / 1000;
  const formatted = formatTimestamp(timestamp, "America/New_York");
  expect(formatted).toContain("2:00");
  expect(formatted).not.toMatch(/EST|EDT|GMT|UTC/);
  expect(formatTimestamp(timestamp, "Asia/Kolkata")).toContain("12:30");
});
