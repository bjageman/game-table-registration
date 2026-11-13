import { useTimezone } from "../../../lib/timezone";
import ModalHeader from "../../../components/ModalHeader";
import { useEffect, useRef, useState } from "react";
import { Download, X } from "lucide-react";
import { isBackdropClick } from "../../../lib/dialogBackdrop";
import { download } from "../../../lib/download";
import { errorMessage, type EventRecord } from "../../../lib/api";

export default function SignupDownload({ event, onAccessError }: {
  event: EventRecord;
  onAccessError: (error: unknown) => boolean;
}) {
  const timezone = useTimezone();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (!open) return;
    const modal = dialog.current;
    modal?.showModal();
    return () => modal?.close();
  }, [open]);

  async function save(format: "pdf" | "csv") {
    setBusy(true);
    setError("");
    try {
      const query = format === "pdf" ? `?timezone=${encodeURIComponent(timezone)}` : "";
      await download(`/events/${encodeURIComponent(event.id)}/signups.${format}${query}`, `signups-${event.id}.${format}`);
      setOpen(false);
    } catch (failure) {
      if (!onAccessError(failure)) setError(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }

  return <>
    <button id={`event-download-${event.id}`} type="button" className="event-icon-action" aria-label="Download event signups" title="Download Signups"
      onClick={() => { setError(""); setOpen(true); }}><Download size={18} aria-hidden="true" /></button>
    {open && <dialog id={`event-download-dialog-${event.id}`} ref={dialog} aria-label={`Download signups for ${event.title}`}
      onClick={(click) => { if (!busy && isBackdropClick(click)) setOpen(false); }}
      onCancel={(cancel) => { cancel.preventDefault(); if (!busy) setOpen(false); }}>
      <ModalHeader>
        <h2>Download signups</h2>
        <button id={`event-download-close-${event.id}`} type="button" aria-label="Close dialog" title="Close" disabled={busy} onClick={() => setOpen(false)}><X size={18} aria-hidden="true" /></button>
      </ModalHeader>
      {error && <p role="alert" className="error">{error}</p>}
      <div className="form-actions">
        <button id={`event-download-pdf-${event.id}`} type="button" disabled={busy} onClick={() => void save("pdf")}>Download PDF</button>
        <button id={`event-download-csv-${event.id}`} type="button" disabled={busy} onClick={() => void save("csv")}>Download CSV</button>
      </div>
    </dialog>}
  </>;
}
