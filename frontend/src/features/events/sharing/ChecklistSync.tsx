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
    <p>Use the browser version to replace the server checkmarks for everyone syncing this link, or use the server version to replace this browser’s checkmarks.</p>
    {checklist.syncError && <p role="alert" className="error">{checklist.syncError}</p>}
    <div className="form-actions">
      <button id="checklist-use-browser" type="button" disabled={checklist.busy} onClick={() => void checklist.resolve("browser")}>Use browser version</button>
      <button id="checklist-use-server" type="button" disabled={checklist.busy} onClick={() => void checklist.resolve("server")}>Use server version</button>
      <button ref={cancel} id="checklist-sync-cancel" type="button" disabled={checklist.busy} onClick={() => void checklist.setSync(false)}>Keep sync off</button>
    </div>
  </dialog>;
}

export default function ChecklistSync({ checklist }: { checklist: Checklist }) {
  return <>
    <div className="public-checklist-sync-controls">
    <label className="public-checklist-sync" htmlFor="public-checklist-sync">
      <input id="public-checklist-sync" type="checkbox" checked={checklist.syncing} disabled={checklist.busy}
        onChange={(event) => void checklist.setSync(event.target.checked)} /> Sync with Server
    </label>
    {checklist.busy && <span role="status">Syncing…</span>}
    </div>
    {checklist.syncError && !checklist.conflict && <p role="alert" className="error">{checklist.syncError}</p>}
    {checklist.conflict && <SyncConflict checklist={checklist} />}
  </>;
}
