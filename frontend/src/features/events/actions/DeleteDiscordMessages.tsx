import { useState } from "react";
import { Trash2 } from "lucide-react";
import ConfirmationDialog from "../../../components/ConfirmationDialog";
import { errorMessage, type EventRecord } from "../../../lib/api";
import { finishDiscordCleanup } from "./discordCleanup";

export default function DeleteDiscordMessages({ event, csrf, onUpdated, onAccessError }: {
  event: EventRecord; csrf: string;
  onUpdated: (event: EventRecord, notice?: string) => void;
  onAccessError: (error: unknown) => boolean;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [remaining, setRemaining] = useState<number>();
  async function remove() {
    if (busy) return;
    setBusy(true); setError("");
    try {
      const saved = await finishDiscordCleanup(event.id, csrf, (progress) => setRemaining(progress.discord_cleanup_remaining));
      setConfirming(false);
      onUpdated(saved, `Discord messages deleted for ${event.title}.`);
    } catch (failure) { if (!onAccessError(failure)) setError(errorMessage(failure)); }
    finally { setBusy(false); }
  }
  return <>
    <button id={`event-delete-discord-messages-${event.id}`} type="button" className="event-icon-action" aria-label="Delete Discord messages" title="Delete Discord Messages"
      onClick={() => { setError(""); setConfirming(true); }}><Trash2 size={18} aria-hidden="true" /></button>
    {confirming && <ConfirmationDialog id={`event-delete-discord-messages-dialog-${event.id}`} title={`Delete Discord messages for ${event.title}?`}
      busy={busy} error={error} status={`Deleting Discord messages…${remaining === undefined ? "" : ` ${remaining} remaining.`}`}
      onCancel={() => setConfirming(false)} onConfirm={() => void remove()}>
      {null}
    </ConfirmationDialog>}
  </>;
}
