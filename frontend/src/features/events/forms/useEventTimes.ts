import { useState } from "react";
import dayjs, { type Dayjs } from "dayjs";
import { resolveLocalTime } from "../../../lib/timezone";

interface WallTime {
  date: string;
  time: string;
}

function wallTime(value: Dayjs): WallTime {
  return { date: value.format("YYYY-MM-DD"), time: value.format("HH:mm") };
}

function localTime(value: WallTime): string {
  return value.date ? `${value.date}T${value.time}` : "";
}

/** One wall-clock value per field, shared by desktop and mobile pickers. */
export function useEventTimes(timezone: string, draft?: { starts_at: number; ends_at?: number | null }) {
  const [reference] = useState(() => dayjs().tz(timezone).add(1, "hour").startOf("hour"));
  const [start, setStart] = useState<WallTime>(() => draft
    ? wallTime(dayjs.unix(draft.starts_at).tz(timezone))
    : { date: "", time: reference.format("HH:mm") });
  const [end, setEnd] = useState<{ override: WallTime | null; time: string }>(() => ({
    override: draft?.ends_at && draft.ends_at - draft.starts_at !== 4 * 3600
      ? wallTime(dayjs.unix(draft.ends_at).tz(timezone)) : null,
    time: reference.format("HH:mm"),
  }));
  const startsAtLocal = localTime(start);
  const resolvedStart = resolveLocalTime(startsAtLocal, timezone).date;
  const defaultEnd = resolvedStart
    ? wallTime(dayjs(resolvedStart).add(4, "hour").tz(timezone)) : { date: "", time: end.time };
  const endWall = end.override ?? defaultEnd;
  const endsAtLocal = localTime(endWall);
  const startsAt = startsAtLocal ? dayjs.tz(startsAtLocal, timezone) : null;
  const endValue = endsAtLocal ? dayjs.tz(endsAtLocal, timezone) : null;

  function updateDesktopStart(value: Dayjs | null) {
    setStart((previous) => value?.isValid() ? wallTime(value) : { ...previous, date: "" });
  }

  function updateMobileDate(value: Dayjs | null) {
    setStart((previous) => ({ ...previous, date: value?.isValid() ? value.format("YYYY-MM-DD") : "" }));
  }

  function updateMobileTime(value: Dayjs | null) {
    if (value?.isValid()) setStart((previous) => ({ ...previous, time: value.format("HH:mm") }));
  }

  function updateDesktopEnd(value: Dayjs | null) {
    setEnd((previous) => ({ ...previous, override: value?.isValid()
      ? wallTime(value) : { date: "", time: previous.time } }));
  }

  function updateEndDate(value: Dayjs | null) {
    setEnd((previous) => ({ ...previous, override: {
      date: value?.isValid() ? value.format("YYYY-MM-DD") : "",
      time: endWall.time,
    } }));
  }

  function updateEndTime(value: Dayjs | null) {
    if (!value?.isValid()) return;
    const time = value.format("HH:mm");
    setEnd((previous) => ({ time, override: endWall.date ? { ...endWall, time } : previous.override }));
  }

  return {
    startsAt, startsAtLocal, endsAtLocal, endValue,
    // Time-only references retain a selection made before choosing a date.
    mobileTime: reference.hour(Number(start.time.slice(0, 2))).minute(Number(start.time.slice(3))),
    mobileEndTime: reference.hour(Number(end.time.slice(0, 2))).minute(Number(end.time.slice(3))),
    updateDesktopStart, updateMobileDate, updateMobileTime,
    updateDesktopEnd, updateEndDate, updateEndTime,
  };
}
