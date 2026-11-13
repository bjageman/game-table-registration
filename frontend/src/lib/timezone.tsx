import { createContext, useContext } from "react";
import dayjs from "dayjs";
import utc from "dayjs/plugin/utc";
import timezonePlugin from "dayjs/plugin/timezone";

dayjs.extend(utc);
dayjs.extend(timezonePlugin);

export const TimezoneContext = createContext<string | null>(null);
export function browserTimezone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}
export function useTimezone(): string {
  return useContext(TimezoneContext) || browserTimezone();
}
export function formatTimestamp(timestamp: number, timezone?: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium", timeStyle: "short", timeZone: timezone,
  }).format(new Date(timestamp * 1000));
}

function wallMinute(date: Date, timezone: string): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone, year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(date);
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}T${values.hour}:${values.minute}`;
}

export function resolveLocalTime(value: string, timezone = browserTimezone()): { date: Date | null; ambiguous: boolean } {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) return { date: null, ambiguous: false };
  const wall = new Date(`${value}Z`);
  if (!Number.isFinite(wall.getTime()) || wall.toISOString().slice(0, 16) !== value) return { date: null, ambiguous: false };
  const candidates = new Map<number, Date>();
  for (const days of [-2, -1, 0, 1, 2]) {
    const sample = new Date(wall.getTime() + days * 86400000);
    const offset = new Date(`${wallMinute(sample, timezone)}Z`).getTime() - sample.getTime();
    const candidate = new Date(wall.getTime() - offset);
    if (wallMinute(candidate, timezone) === value) candidates.set(candidate.getTime(), candidate);
  }
  return { date: candidates.size === 1 ? [...candidates.values()][0] : null, ambiguous: candidates.size > 1 };
}
