import { useEffect, useRef, useState } from "react";
import {
  api,
  ApiError,
  errorMessage,
  mutationOptions,
  type EventRecord,
} from "./api";

export interface PublicationActions {
  csrf: string;
  onUpdated: (event: EventRecord) => void;
  onUncertain: (event: EventRecord, message: string) => void;
  onAccessError: (error: unknown) => boolean;
}

export default function PublishEvent({
  event,
  csrf,
  onUpdated,
  onUncertain,
  onAccessError,
}: PublicationActions & { event: EventRecord }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inFlight = useRef(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const [now, setNow] = useState(Date.now);
  const scheduled = Boolean(event.opens_at);
  const expired = scheduled
    ? (event.opens_at ?? 0) * 1000 <= now
    : event.starts_at * 1000 <= now + event.duration_hours * 3600000;

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!confirming) return;
    const modal = dialog.current;
    const returnFocus = trigger.current;
    modal?.showModal();
    cancel.current?.focus();
    return () => {
      modal?.close();
      returnFocus?.focus();
    };
  }, [confirming]);

  async function publish() {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      const result = await api<EventRecord>(
        `/events/${encodeURIComponent(event.id)}/${scheduled ? "schedule" : "publish"}`,
        mutationOptions(csrf),
      );
      setConfirming(false);
      onUpdated(result);
    } catch (failure) {
      if (onAccessError(failure)) return;
      if (
        failure instanceof ApiError &&
        (failure.status === 400 || failure.status === 422)
      ) {
        setError(errorMessage(failure));
      } else {
        setConfirming(false);
        onUncertain(event, errorMessage(failure));
      }
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  return (
    <>
      <button
        ref={trigger}
        className="primary"
        disabled={expired}
        onClick={() => {
          setError("");
          setConfirming(true);
        }}
      >
