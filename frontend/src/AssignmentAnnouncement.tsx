import { useEffect, useState } from "react";
import DiscordLink from "./DiscordLink";
import ConfirmationDialog from "./ConfirmationDialog";
import { api, errorMessage, mutationOptions, type EventRecord } from "./api";
import LoadingIndicator from "./LoadingIndicator";

interface Delivery { status: "pending" | "sent" | "needs_review" | "unavailable" | "deleted"; error: string | null; url: string | null; update_pending?: boolean; update_error?: string | null; }

export default function AssignmentAnnouncement({ event, csrf, refreshToken, readOnly = false, onAccessError }: {
  event: EventRecord; csrf: string; refreshToken: number; readOnly?: boolean; onAccessError: (error: unknown) => boolean;
}) {
  const [delivery, setDelivery] = useState<Delivery>();
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      try {
        const value = await api<Delivery>(`/events/${encodeURIComponent(event.id)}/announcement`, { signal: controller.signal });
        if (!controller.signal.aborted) {
          setDelivery(value); setError("");
          if (!event.archived_at) timer = setTimeout(() => void load(), value.update_pending || value.status === "pending" ? 5000 : 15000);
        }
      } catch (failure) { if (!controller.signal.aborted && !onAccessError(failure)) setError(errorMessage(failure)); }
    }
    void load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [event.id, event.archived_at, refreshToken, attempt, onAccessError]);
  async function retry() {
    if (busy) return;
    setBusy(true); setError("");
    try {
      const value = await api<Delivery>(`/events/${encodeURIComponent(event.id)}/announcement/retry`, mutationOptions(csrf, { confirm_repost: true }));
      setDelivery(value); setConfirming(false); setAttempt((n) => n + 1);
    } catch (failure) { if (!onAccessError(failure)) setError(errorMessage(failure)); }
    finally { setBusy(false); }
  }
  return <div className="announcement-status">
    {!delivery && !error && <p><LoadingIndicator label="Loading announcement status…" /></p>}
    {error && <p role="alert" className="error">{error}</p>}
    {delivery?.status === "sent" && delivery.url && <p><DiscordLink url={delivery.url} label="View Assignment Announcement">View Assignment Announcement</DiscordLink></p>}
    {delivery?.update_pending && <p role="status">Updating Discord assignments…</p>}
    {delivery?.update_error && <p role="alert" className="error">Could not update Discord assignments: {delivery.update_error}</p>}
    {delivery?.status === "pending" && <p role="status">Assignment announcement queued for Discord.</p>}
    {delivery?.status === "deleted" && <p>Assignment announcement removed from Discord.</p>}
    {delivery?.error && <p className="error">{delivery.error}</p>}
    {!readOnly && delivery && !event.archived_at && (delivery.status === "needs_review" || delivery.status === "unavailable" || delivery.error) && <button type="button" onClick={() => setConfirming(true)}>{delivery.status === "unavailable" ? "Announce Assignments" : "Retry Announcement"}</button>}
    {confirming && <ConfirmationDialog title="Announce assignments?" busy={busy} error={error}
      onCancel={() => setConfirming(false)} onConfirm={() => void retry()}>
      <p>{delivery?.status === "unavailable" ? "Posts the saved table placements to Discord." : "Check Discord for an existing announcement before confirming a retry. This sends the saved placements and does not redraw them."}</p>
    </ConfirmationDialog>}
  </div>;
}
