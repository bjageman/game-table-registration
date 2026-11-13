import ModalHeader from "./ModalHeader";
import { isBackdropClick } from "../lib/dialogBackdrop";
import { useEffect, useId, useRef, type ReactNode } from "react";
import LoadingIndicator from "./LoadingIndicator";
import { X } from "lucide-react";

export default function ConfirmationDialog({
  id, title, children, busy, error, status, onCancel, onConfirm, showClose = true,
}: {
  id?: string;
  title: string;
  children: ReactNode;
  busy: boolean;
  error: string;
  status?: string;
  showClose?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const heading = useId();
  const dialogId = id ?? `confirmation-dialog-${heading}`;
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
    <dialog id={dialogId} onClick={(event) => { if (!busy && isBackdropClick(event)) onCancel(); }} ref={dialog} aria-labelledby={heading} aria-busy={busy}
      onCancel={(event) => { event.preventDefault(); if (!busy) onCancel(); }}>
      <ModalHeader>
        <h2 id={heading}>{title}</h2>
        {showClose && <button id={`${dialogId}-close`} type="button" disabled={busy} aria-label="Close dialog" title="Close" onClick={onCancel}><X size={18} aria-hidden="true" /></button>}
      </ModalHeader>
      {children}
      {error && <p role="alert" className="error">{error}</p>}
      {busy && status && <p><LoadingIndicator label={status} /></p>}
      <div className="form-actions confirmation-actions">
        <button id={`${dialogId}-cancel`} ref={cancel} type="button" disabled={busy} onClick={onCancel}>Cancel</button>
        <button id={`${dialogId}-confirm`} type="button" className="primary" disabled={busy} onClick={onConfirm}>Confirm</button>
      </div>
    </dialog>
  );
}
