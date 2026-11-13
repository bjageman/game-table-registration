import { useRef } from "react";
import useFittedText from "../hooks/useFittedText";
import { formatTimestamp, useTimezone } from "../lib/timezone";

export default function EventDateLine({ label, timestamp }: { label: string; timestamp: number | null }) {
  const timezone = useTimezone();
  const text = timestamp == null ? "-" : formatTimestamp(timestamp, timezone);
  const row = useRef<HTMLDivElement>(null);
  useFittedText(row, `${label}:${text}`);
  return <div ref={row} className="event-date-line">
    <dt>{label}</dt>
    <dd>{timestamp == null ? text : <time dateTime={new Date(timestamp * 1000).toISOString()}>{text}</time>}</dd>
  </div>;
}
