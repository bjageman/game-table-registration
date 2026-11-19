import { useRef } from "react";
import useDialog from "../../../hooks/useDialog";
import ModalHeader from "../../../components/ModalHeader";
import type { usePublicChecklist } from "./usePublicChecklist";

type Checklist = ReturnType<typeof usePublicChecklist>;

function SyncConflict({ checklist }: { checklist: Checklist }) {
  const cancel = useRef<HTMLButtonElement>(null);
  const dialog = useDialog(true, cancel);
  return <dialog id="public-checklist-sync-conflict" ref={dialog} aria-labelledby="checklist-sync-heading"
    aria-busy={checklist.busy} onCancel={(event) => { event.preventDefault(); if (!checklist.busy) void checklist.setSync(false); }}>
    <ModalHeader><h2 id="checklist-sync-heading">Choose checklist version</h2></ModalHeader>
    <p>The browser and server checkmarks differ. Which version should both use?</p>
    {checklist.syncError && <p role="alert" className="error">{checklist.syncError}</p>}
    <div className="form-actions checklist-sync-actions">
      <button id="checklist-use-browser" type="button" disabled={checklist.busy} onClick={() => void checklist.resolve("browser")}>Browser</button>
      <button id="checklist-use-server" type="button" disabled={checklist.busy} onClick={() => void checklist.resolve("server")}>Server</button>
      <button ref={cancel} id="checklist-sync-cancel" type="button" disabled={checklist.busy} onClick={() => void checklist.setSync(false)}>Cancel</button>
    </div>
  </dialog>;
}

export default function ChecklistSync({ checklist }: { checklist: Checklist }) {
  return (
    <div className="public-checklist-sync-controls">
    <label className="public-checklist-sync" htmlFor="public-checklist-sync">
      <input id="public-checklist-sync" type="checkbox" checked={checklist.syncing} aria-disabled={checklist.busy}
        disabled={checklist.busy && checklist.disabled}
        onChange={(event) => void checklist.setSync(event.target.checked)} /> Sync with Server
    </label>
    {checklist.busy && checklist.disabled && <span role="status">Syncing…</span>}
    </div>
  );
}

export function ChecklistSyncFeedback({ checklist }: { checklist: Checklist }) {
  return <>
    {checklist.syncError && !checklist.conflict && <p role="alert" className="error">{checklist.syncError}</p>}
    {checklist.conflict && <SyncConflict checklist={checklist} />}
  </>;
}
