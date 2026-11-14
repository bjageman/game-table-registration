import { useEffect, useRef, type RefObject } from "react";

/** Open a native dialog and restore focus to its trigger when it closes. */
export default function useDialog(open = true, initialFocus?: RefObject<HTMLElement | null>) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (!open) return;
    const modal = dialog.current;
    if (!modal) return;
    const trigger = document.activeElement;
    modal.showModal();
    initialFocus?.current?.focus();
    return () => {
      modal.close();
      if (trigger instanceof HTMLElement && trigger.isConnected) trigger.focus();
    };
  }, [open, initialFocus]);
  return dialog;
}
