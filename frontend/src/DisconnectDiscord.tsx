import { useRef, useState } from "react";
import ConfirmationDialog from "./ConfirmationDialog";
import { api, errorMessage, mutationOptions } from "./api";

export default function DisconnectDiscord({ csrf, disabled, onDisconnected, onAccessError, onBusyChange }: {
  csrf: string; disabled: boolean;
  onDisconnected: () => Promise<void>;
  onAccessError: (error: unknown) => boolean;
  onBusyChange: (busy: boolean) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inFlight = useRef(false);
  async function disconnect() {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); onBusyChange(true); setError("");
    try {
      await api<void>("/settings", { ...mutationOptions(csrf), method: "DELETE" });
      await onDisconnected();
      setConfirming(false);
    } catch (failure) { if (!onAccessError(failure)) setError(errorMessage(failure)); }
    finally { inFlight.current = false; setBusy(false); onBusyChange(false); }
  }
  return <>
    <button type="button" disabled={disabled || busy} onClick={() => { setError(""); setConfirming(true); }}>Disconnect</button>
    {confirming && <ConfirmationDialog title="Disconnect Discord?" busy={busy} error={error} status="Disconnecting…"
      onCancel={() => setConfirming(false)} onConfirm={() => void disconnect()}>{null}</ConfirmationDialog>}
  </>;
}
