import { useEffect, useState } from "react";
import DiscordLink from "./DiscordLink";
import ConfirmationDialog from "./ConfirmationDialog";
import { api, errorMessage, mutationOptions, type EventRecord } from "./api";

interface Delivery { status: "pending" | "sent" | "needs_review" | "unavailable"; error: string | null; url: string | null; }

export default function AssignmentAnnouncement({ event, csrf, refreshToken, onAccessError }: {
  event: EventRecord; csrf: string; refreshToken: number; onAccessError: (error: unknown) => boolean;
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
          if (value.status === "pending") timer = setTimeout(() => void load(), 5000);
        }
      } catch (failure) { if (!controller.signal.aborted && !onAccessError(failure)) setError(errorMessage(failure)); }
    }
    void load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [event.id, refreshToken, attempt, onAccessError]);
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
    {error && <p role="alert" className="error">{error}</p>}
    {delivery?.status === "sent" && delivery.url && <p><DiscordLink url={delivery.url} label="View Assignment Announcement">View Assignment Announcement</DiscordLink></p>}
    {delivery?.status === "pending" && <p role="status">Assignment announcement queued for Discord.</p>}
    {delivery?.error && <p className="error">{delivery.error}</p>}
    {delivery && (delivery.status === "needs_review" || delivery.status === "unavailable" || delivery.error) && <button type="button" onClick={() => setConfirming(true)}>{delivery.status === "unavailable" ? "Announce Assignments" : "Retry Announcement"}</button>}
    {confirming && <ConfirmationDialog title="Announce assignments?" busy={busy} error={error}
      onCancel={() => setConfirming(false)} onConfirm={() => void retry()}>
      <p>{delivery?.status === "unavailable" ? "Posts the saved table placements to Discord." : "Check Discord for an existing announcement before confirming a retry. This sends the saved placements and does not redraw them."}</p>
    </ConfirmationDialog>}
  </div>;
}
