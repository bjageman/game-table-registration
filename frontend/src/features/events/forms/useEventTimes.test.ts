import { act, renderHook } from "@testing-library/react";
import { expect, it } from "vitest";
import dayjs from "dayjs";
import { resolveLocalTime } from "../../../lib/timezone";
import { useEventTimes } from "./useEventTimes";

const zone = "America/New_York";

it("shares desktop and mobile edits, including a time selected before its date", () => {
  const { result } = renderHook(() => useEventTimes(zone));
  act(() => result.current.updateMobileTime(dayjs("2090-01-01T18:15")));
  expect(result.current.startsAtLocal).toBe("");
  act(() => result.current.updateMobileDate(dayjs("2090-06-14")));
  expect(result.current.startsAtLocal).toBe("2090-06-14T18:15");
  act(() => result.current.updateDesktopStart(dayjs("2090-06-15T20:30")));
  act(() => result.current.updateMobileTime(dayjs("2090-01-01T21:45")));
  expect(result.current.startsAtLocal).toBe("2090-06-15T21:45");
  act(() => result.current.updateMobileDate(null));
  expect(result.current.startsAt).toBeNull();
  act(() => result.current.updateMobileDate(dayjs("2090-06-16")));
  expect(result.current.startsAtLocal).toBe("2090-06-16T21:45");
});

it.each([
  ["2027-03-13T23:00", "2027-03-14T04:00"],
  ["2027-11-06T23:00", "2027-11-07T02:00"],
])("defaults to four elapsed hours across DST starting %s", (start, end) => {
  const { result } = renderHook(() => useEventTimes(zone));
  act(() => result.current.updateDesktopStart(dayjs(start)));
  expect(result.current.endsAtLocal).toBe(end);
  expect(resolveLocalTime(end, zone).date!.getTime() - resolveLocalTime(start, zone).date!.getTime()).toBe(4 * 3600000);
});

it.each(["2027-03-14T02:30", "2027-11-07T01:30"])("preserves invalid or ambiguous wall time %s for validation", (local) => {
  const { result } = renderHook(() => useEventTimes(zone));
  act(() => result.current.updateMobileTime(dayjs(`2027-01-01T${local.slice(11)}`)));
  act(() => result.current.updateMobileDate(dayjs(`${local.slice(0, 10)}T12:00`)));
  expect(result.current.startsAtLocal).toBe(local);
  expect(resolveLocalTime(result.current.startsAtLocal, zone).date).toBeNull();
  expect(result.current.endsAtLocal).toBe("");
});

it("preserves a custom end across start changes and edits it from either layout", () => {
  const { result } = renderHook(() => useEventTimes(zone));
  act(() => result.current.updateDesktopStart(dayjs("2090-06-14T19:00")));
  act(() => result.current.updateEndDate(dayjs("2090-06-16")));
  act(() => result.current.updateEndTime(dayjs("2090-01-01T18:15")));
  act(() => result.current.updateDesktopStart(dayjs("2090-06-15T19:00")));
  expect(result.current.endsAtLocal).toBe("2090-06-16T18:15");
  act(() => result.current.updateDesktopEnd(dayjs("2090-06-17T20:00")));
  act(() => result.current.updateEndTime(dayjs("2090-01-01T21:30")));
  expect(result.current.endsAtLocal).toBe("2090-06-17T21:30");
  act(() => result.current.updateDesktopEnd(null));
  expect(result.current.endsAtLocal).toBe("");
});
