import { useRef, useState, type FormEvent } from "react";
import { X } from "lucide-react";
import ModalHeader from "../../components/ModalHeader";
import useDialog from "../../hooks/useDialog";
import { isBackdropClick } from "../../lib/dialogBackdrop";
import { api, errorMessage, mutationOptions } from "../../lib/api";

export default function EditOrganization({ organization, csrf, onSaved, onClose, onAccessError }: {
  organization: { id: string; name: string }; csrf: string;
  onSaved: (name: string) => Promise<void>; onClose: () => void;
  onAccessError: (error: unknown) => boolean;
}) {
  const [name, setName] = useState(organization.name);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inFlight = useRef(false);
  const dialog = useDialog();
  function close() { if (!inFlight.current) onClose(); }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (inFlight.current || !name.trim()) return;
    inFlight.current = true; setBusy(true); setError("");
    try {
      const updated = await api<{ name: string }>(`/organizations/${encodeURIComponent(organization.id)}`, {
        ...mutationOptions(csrf, { name: name.trim() }), method: "PUT",
      });
      await onSaved(updated.name);
      onClose();
    } catch (failure) { if (!onAccessError(failure)) setError(errorMessage(failure)); }
    finally { inFlight.current = false; setBusy(false); }
  }
  return <dialog id="organization-edit-dialog" ref={dialog} aria-labelledby="organization-edit-heading"
    onCancel={(event) => { event.preventDefault(); close(); }}
    onClick={(event) => { if (isBackdropClick(event)) close(); }}>
    <ModalHeader>
      <h2 id="organization-edit-heading">Edit organization</h2>
      <button type="button" aria-label="Close edit organization" title="Close" disabled={busy} onClick={close}><X size={18} aria-hidden="true" /></button>
    </ModalHeader>
    <form onSubmit={(event) => void save(event)}>
      <label htmlFor="organization-edit-name">Organization name</label>
      <input id="organization-edit-name" autoFocus required maxLength={100} value={name} disabled={busy} onChange={(event) => setName(event.target.value)} />
      {error && <p role="alert" className="error">{error}</p>}
      <div className="form-actions">
        <button type="button" disabled={busy} onClick={close}>Cancel</button>
        <button type="submit" className="primary" disabled={busy || !name.trim()}>{busy ? "Saving…" : "Save"}</button>
      </div>
    </form>
  </dialog>;
}
