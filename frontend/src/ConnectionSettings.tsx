import { useEffect, useId, useState, type FormEvent } from "react";
import TextField from "@mui/material/TextField";
import { RefreshCw } from "lucide-react";
import Tabs from "@mui/material/Tabs";
import Tab from "@mui/material/Tab";
import MenuItem from "@mui/material/MenuItem";
import DisconnectDiscord from "./DisconnectDiscord";
import AssignmentSettings from "./AssignmentSettings";
import { api, errorMessage, mutationOptions } from "./api";

interface Choice { id: string; name: string; }
interface Selection { guild_id: string; channel_id: string; guild_name: string; channel_name: string; }
interface Setup { disconnected?: boolean; selection: Selection | null; guilds: Choice[]; install_url: string; }

export default function ConnectionSettings({ csrf, onSaved, onAccessError }: {
  csrf: string;
  onSaved: () => Promise<void>;
  onAccessError: (error: unknown) => boolean;
}) {
  const tabId = useId();
  const [connecting, setConnecting] = useState(false);
  const [tab, setTab] = useState("discord");
  const [setup, setSetup] = useState<Setup>();
  const [guildId, setGuildId] = useState("");
  const [channelId, setChannelId] = useState("");
  const [channels, setChannels] = useState<Choice[]>();
  const [error, setError] = useState("");
  const [channelError, setChannelError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [channelAttempt, setChannelAttempt] = useState(0);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    api<Setup>("/settings", { signal: controller.signal })
      .then((value) => {
        if (!controller.signal.aborted) {
          setSetup(value); setGuildId(value.selection?.guild_id ?? "");
          setChannelId(value.selection?.channel_id ?? ""); setError("");
        }
      })
      .catch((failure) => { if (!controller.signal.aborted && !onAccessError(failure)) setError(errorMessage(failure)); });
    return () => controller.abort();
  }, [attempt, onAccessError]);
  useEffect(() => {
    if (!guildId) return;
    const controller = new AbortController();
    api<{ channels: Choice[] }>(`/settings/channels?guild_id=${encodeURIComponent(guildId)}`, { signal: controller.signal })
      .then((value) => {
        if (!controller.signal.aborted) {
          setChannels(value.channels); setChannelError("");
          setChannelId((current) => value.channels.some((c) => c.id === current) ? current : "");
        }
      })
      .catch((failure) => {
        if (!controller.signal.aborted && !onAccessError(failure)) setChannelError(errorMessage(failure));
      });
    return () => controller.abort();
  }, [guildId, channelAttempt, onAccessError]);
  async function save(event: FormEvent) {
    event.preventDefault();
    if (saving || !guildId || !channelId) return;
    setSaving(true); setSaved(false); setError("");
    try {
      const selection = await api<Selection>("/settings", { ...mutationOptions(csrf, { guild_id: guildId, channel_id: channelId }), method: "PUT" });
      setSetup((current) => current ? { ...current, selection, disconnected: false } : current);
      await onSaved();
      setSaved(true);
    } catch (failure) { if (!onAccessError(failure)) setError(errorMessage(failure)); }
    finally { setSaving(false); }
  }
  const installUrl = setup ? setup.install_url + (guildId ? `&guild_id=${encodeURIComponent(guildId)}&disable_guild_select=true` : "") : "";
  return <section className="panel settings-panel" aria-labelledby="settings-heading">
    <div className="section-heading"><h2 id="settings-heading">Settings</h2></div>
    <Tabs className="settings-tabs" value={tab} onChange={(_event, value: string) => setTab(value)} aria-label="Settings">
      <Tab label="Discord" value="discord" id={`${tabId}-discord-tab`} aria-controls={`${tabId}-discord-panel`} />
      <Tab label="Assignments" value="assignments" id={`${tabId}-assignments-tab`} aria-controls={`${tabId}-assignments-panel`} />
    </Tabs>
    <div role="tabpanel" id={`${tabId}-discord-panel`} aria-labelledby={`${tabId}-discord-tab`} hidden={tab !== "discord"}>
    {!setup && !error && <p role="status">Loading settings…</p>}
    {error && <p role="alert" className="error">{error}{!setup && <button type="button" onClick={() => setAttempt((n) => n + 1)}>Retry settings</button>}</p>}
    {setup && <>
      <div className="form-actions settings-connections">
        {setup.disconnected && !connecting && <button type="button" onClick={() => setConnecting(true)}>Connect</button>}
        {(!setup.disconnected || connecting) && (!setup.selection || setup.selection.guild_id !== guildId) && <a className="button" href={installUrl} target="_blank" rel="noreferrer">Add TableSignup to Discord<span className="sr-only"> (opens in a new tab)</span></a>}
        {setup.selection && <DisconnectDiscord csrf={csrf} disabled={saving} onAccessError={onAccessError} onBusyChange={setSaving}
          onDisconnected={async () => {
            await onSaved();
            setSetup((current) => current ? { ...current, selection: null, disconnected: true } : current);
            setConnecting(false); setGuildId(""); setChannelId(""); setChannels(undefined); setChannelError(""); setSaved(false); setError("");
          }} />}
      </div>
      {(!setup.disconnected || connecting) && !setup.guilds.length && <p className="help">No manageable servers found. Refresh your server list to grant Discord server access.</p>}
      {(!setup.disconnected || connecting) && <form onSubmit={(event) => void save(event)} aria-label="Discord settings">
        <div className="form-grid">
          <TextField select label="Discord Server" value={guildId} fullWidth disabled={saving}
            slotProps={{ inputLabel: { shrink: true } }}
            onChange={(event) => {
              setGuildId(event.target.value); setChannelId(""); setChannels(undefined);
              setChannelError(""); setSaved(false);
            }}>
            <MenuItem value="">Choose a server</MenuItem>
            {setup.guilds.map((g) => <MenuItem key={g.id} value={g.id}>{g.name}</MenuItem>)}
          </TextField>
          <div className="signup-channel-field">
          <TextField select label="Signup Channel" value={channels ? channelId : ""} fullWidth disabled={saving || !channels?.length}
            slotProps={{ inputLabel: { shrink: true } }}
            onChange={(event) => { setChannelId(event.target.value); setSaved(false); }}>
            <MenuItem value="">Choose a channel</MenuItem>
            {(channels ?? []).map((c) => <MenuItem key={c.id} value={c.id}>#{c.name}</MenuItem>)}
          </TextField>
          <a className="button settings-refresh" href="/api/auth/login?return_to=settings" aria-label="Refresh Server List" title="Refresh Server List">
            <RefreshCw size={18} aria-hidden="true" />
          </a>
          </div>
        </div>
        {guildId && !channels && !channelError && <p role="status">Loading channels…</p>}
        {channelError && <p role="alert" className="error">Could not load channels. {channelError}</p>}
        {guildId && <>
          <p className="help">If channels are missing, disconnect from Discord and reconnect.</p>
          <button type="button" disabled={saving} onClick={() => { setChannelError(""); setChannels(undefined); setChannelAttempt((n) => n + 1); }}>Refresh Channels</button>
        </>}
        {channels?.length === 0 && <p className="help">No eligible text channels found.</p>}
        {saved && <p role="status">Settings saved.</p>}
        <div className="form-actions"><button className="primary" type="submit" disabled={saving || !guildId || !channelId || !channels?.some((c) => c.id === channelId)}>{saving ? "Saving…" : "Save"}</button></div>
      </form>}
    </>}
    </div>
    <div role="tabpanel" id={`${tabId}-assignments-panel`} aria-labelledby={`${tabId}-assignments-tab`} hidden={tab !== "assignments"}>
      {setup?.selection ? <AssignmentSettings key={setup.selection.guild_id} csrf={csrf} onAccessError={onAccessError} />
        : setup ? <button type="button" onClick={() => { setTab("discord"); setConnecting(true); }}>Connect Discord</button>
        : <p role="status">Loading settings…</p>}
    </div>
  </section>;
}
