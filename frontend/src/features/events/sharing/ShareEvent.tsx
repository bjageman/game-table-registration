import { useEffect, useRef, useState } from "react";
import { Share2, X } from "lucide-react";
import { api, errorMessage, mutationOptions } from "../../../lib/api";
import { isBackdropClick } from "../../../lib/dialogBackdrop";

export default function ShareEvent({ eventId, csrf, onAccessError }: {
  eventId: string; csrf: string; onAccessError: (error: unknown) => boolean;
}) {
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  async function copyLink() {
    try { await navigator.clipboard.writeText(url); setCopied(true); }
    catch { setError("Could not copy. Select and copy the link above."); }
  }
  useEffect(() => {
    if (!open) return;
    const modal = dialog.current;
    const trigger = document.activeElement;
    modal?.showModal();
    let active = true;
    api<{ path: string }>(`/events/${eventId}/share`, mutationOptions(csrf))
      .then((result) => { if (active) setUrl(new URL(result.path, window.location.origin).href); })
      .catch((failure) => { if (active && !onAccessError(failure)) setError(errorMessage(failure)); });
    return () => { active = false; modal?.close(); if (trigger instanceof HTMLElement) trigger.focus(); };
  }, [open, eventId, csrf, onAccessError]);
  return <>
    <button type="button" className="event-icon-action" aria-label="Share event" title="Share event"
      onClick={() => { setError(""); setCopied(false); setUrl(""); setOpen(true); }}><Share2 size={18} aria-hidden="true" /></button>
    {open && <dialog ref={dialog} aria-labelledby="share-event-heading"
      onCancel={(event) => { event.preventDefault(); setOpen(false); }}
      onClick={(event) => { if (isBackdropClick(event)) setOpen(false); }}>
      <div className="event-modal-header"><h2 id="share-event-heading">Share table assignments</h2>
        <button type="button" aria-label="Close sharing" onClick={() => setOpen(false)}><X size={18} aria-hidden="true" /></button>
      </div>
      <p>Anyone with this link can view the current table assignments and waitlists without signing in.</p>
      {error && <p role="alert" className="error">{error}</p>}
      {!url && !error && <p role="status">Preparing link…</p>}
      {url && <>
        <label className="share-link-label">Public link<input aria-label="Public link" readOnly value={url} onFocus={(event) => event.target.select()} /></label>
        <div className="form-actions">
          <button type="button" onClick={() => void copyLink()}>{copied ? "Copied" : "Copy link"}</button>
          <a className="button" href={url} target="_blank" rel="noopener noreferrer">Open public view</a>
        </div>
      </>}
    </dialog>}
  </>;
}
