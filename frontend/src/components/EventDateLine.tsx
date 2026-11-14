import { useRef, type ReactNode } from "react";
import useFittedText from "../hooks/useFittedText";
import { formatTimestamp, useTimezone } from "../lib/timezone";

export default function EventDateLine({ label, timestamp }: { label: string; timestamp: number | null }) {
  const timezone = useTimezone();
  const text = timestamp == null ? "-" : formatTimestamp(timestamp, timezone);
  return <div className="event-date-line">
    <dt>{label}</dt>
    <dd>{timestamp == null ? text : <time dateTime={new Date(timestamp * 1000).toISOString()}>{text}</time>}</dd>
  </div>;
}

export function EventDateDetails({ children }: { children: ReactNode }) {
  const details = useRef<HTMLDListElement>(null);
  const timezone = useTimezone();
  useFittedText(details, { children, timezone }, ".event-date-line");
  return <dl ref={details} className="event-details">{children}</dl>;
}
