import { useRef, useState } from "react";
import { Archive } from "lucide-react";
import ConfirmationDialog from "../../../components/ConfirmationDialog";
import { api, errorMessage, mutationOptions, type EventRecord } from "../../../lib/api";
import useRememberedCheckbox from "../../../hooks/useRememberedCheckbox";
import { finishDiscordCleanup, type CleanupProgress } from "./discordCleanup";

export default function ArchiveEvent({ event, csrf, onUpdated, onAccessError }: {
  event: EventRecord; csrf: string;
  onUpdated: (event: EventRecord, notice?: string) => void;
  onAccessError: (error: unknown) => boolean;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("Archiving…");
  const [deleteMessages, setDeleteMessages] = useRememberedCheckbox("delete-discord-messages-on-archive");
  const inFlight = useRef(false);
  async function archive() {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError(""); setStatus("Archiving…");
    let archived: EventRecord | undefined;
    try {
      const saved = await api<CleanupProgress>(`/events/${encodeURIComponent(event.id)}/archive${deleteMessages ? "?delete_discord_messages=true" : ""}`, mutationOptions(csrf));
      archived = saved;
      const completed = deleteMessages
        ? await finishDiscordCleanup(event.id, csrf, (progress) => {
          archived = progress;
          setStatus(`Deleting Discord messages… ${progress.discord_cleanup_remaining} remaining.`);
        }, saved)
        : saved;
      setConfirming(false);
      const cleanupNotice = !deleteMessages && (saved.discord_cleanup_error || saved.discord_cleanup_remaining)
        ? ` Discord cleanup remains unfinished. Use Delete Discord Messages to retry.`
        : "";
      onUpdated(completed, `Event archived: ${event.title}.${cleanupNotice}`);
    } catch (failure) {
      if (!onAccessError(failure)) {
        if (archived) {
          setConfirming(false);
          onUpdated(archived, `Event archived. Discord cleanup paused: ${errorMessage(failure)} Show Archived, then use Delete Discord messages to retry.`);
        } else setError(errorMessage(failure));
      }
    }
    finally { inFlight.current = false; setBusy(false); }
  }
  return <>
    <button id={`event-archive-${event.id}`} type="button" className="event-icon-action" aria-label="Archive event" title="Archive Event"
      onClick={() => { setError(""); setConfirming(true); }}><Archive size={18} aria-hidden="true" /></button>
    {confirming && <ConfirmationDialog id={`event-archive-dialog-${event.id}`} title={`Archive ${event.title}?`} busy={busy} error={error} status={status}
      onCancel={() => setConfirming(false)} onConfirm={() => void archive()}>
      {null}
      <label className="delete-poll-option"><input type="checkbox" checked={deleteMessages} disabled={busy}
        onChange={(change) => setDeleteMessages(change.target.checked)} /> Also delete the signup and assignment messages on Discord</label>
    </ConfirmationDialog>}
  </>;
}
