import { useEffect, useRef, useState } from "react";
import {
  api,
  errorMessage,
  type EventRecord,
  type ModeratorSession,
} from "./api";
import EventList from "./EventList";
import EventForm from "./EventForm";
import Schedules from "./Schedules";

export interface DashboardProps {
  session: ModeratorSession;
  onAccessError: (error: unknown) => boolean;
}

export default function Dashboard({ session, onAccessError }: DashboardProps) {
  const [events, setEvents] = useState<EventRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [creating, setCreating] = useState(false);
  const [showSchedules, setShowSchedules] = useState(false);
  const [editing, setEditing] = useState<EventRecord | undefined>();
  const [notice, setNotice] = useState("");
  const noticeElement = useRef<HTMLParagraphElement>(null);
  const createButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (notice) noticeElement.current?.focus();
  }, [notice]);

  function created(event: EventRecord) {
    setEvents((rows) =>
      [...rows.filter((row) => row.id !== event.id), event].sort(
        (a, b) => a.starts_at - b.starts_at,
      ),
    );
    setCreating(false);
    setEditing(undefined);
    setNotice(
      `Draft saved: ${event.title}. Nothing has been posted to Discord.`,
    );
  }

  function updated(event: EventRecord) {
    setEvents((rows) => rows.map((row) => (row.id === event.id ? event : row)));
    setNotice(
      `${event.status === "scheduled" ? "Signups scheduled" : "Poll published"}: ${event.title}.`,
