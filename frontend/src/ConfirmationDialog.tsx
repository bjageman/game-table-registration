import { useEffect, useId, useRef, type ReactNode } from "react";

export default function ConfirmationDialog({
  title, children, busy, error, status, onCancel, onConfirm,
}: {
  title: string;
  children: ReactNode;
  busy: boolean;
  error: string;
  status?: string;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const heading = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const modal = dialog.current;
    const trigger = document.activeElement;
    modal?.showModal();
    cancel.current?.focus();
    return () => {
      modal?.close();
      if (trigger instanceof HTMLElement && trigger.isConnected) trigger.focus();
    };
  }, []);
  return (
    <dialog ref={dialog} aria-labelledby={heading} aria-busy={busy}
      onCancel={(event) => { event.preventDefault(); if (!busy) onCancel(); }}>
      <h2 id={heading}>{title}</h2>
      {children}
      {error && <p role="alert" className="error">{error}</p>}
      {busy && status && <p role="status">{status}</p>}
      <div className="form-actions confirmation-actions">
        <button ref={cancel} type="button" disabled={busy} onClick={onCancel}>Cancel</button>
        <button type="button" className="primary" disabled={busy} onClick={onConfirm}>Confirm</button>
      </div>
    </dialog>
  );
}
