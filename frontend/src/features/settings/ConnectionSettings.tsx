import { useEffect, useId, useState, type FormEvent } from "react";
import { FormField } from "../../components/FormFields";
import { RefreshCw } from "lucide-react";
import Dialog from "@mui/material/Dialog";
import DialogTitle from "@mui/material/DialogTitle";
import DialogContent from "@mui/material/DialogContent";
import List from "@mui/material/List";
import ListItemButton from "@mui/material/ListItemButton";
import Tabs from "@mui/material/Tabs";
import Tab from "@mui/material/Tab";
import MenuItem from "@mui/material/MenuItem";
import DisconnectDiscord from "./DisconnectDiscord";
import AssignmentSettings from "./AssignmentSettings";
import { api, errorMessage, mutationOptions } from "../../lib/api";
import LoadingIndicator from "../../components/LoadingIndicator";
import OrganizationSettings from "./OrganizationSettings";

interface Choice { id: string; name: string; }
interface Selection { guild_id: string; channel_id: string; guild_name: string; channel_name: string; }
interface Setup { disconnected?: boolean; selection: Selection | null; connect_url: string; organization_role?: "user" | "editor" | "admin" | null; }

export default function ConnectionSettings({ csrf, userId = "", organizationId, onSaved, onAccessError }: {
  csrf: string;
  userId?: string;
  organizationId?: string;
  onSaved: () => Promise<void>;
  onAccessError: (error: unknown) => boolean;
}) {
  const tabId = useId();
  const [tab, setTab] = useState("discord");
  const [setup, setSetup] = useState<Setup>();
  const [guilds, setGuilds] = useState<Choice[]>([]);
  const [choosingServer, setChoosingServer] = useState(false);
  const [refreshingServers, setRefreshingServers] = useState(false);
  const [guildId, setGuildId] = useState("");
  const [channelId, setChannelId] = useState("");
  const [channels, setChannels] = useState<Choice[]>();
  const [error, setError] = useState("");
  const [channelError, setChannelError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [channelAttempt, setChannelAttempt] = useState(0);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    api<Setup>("/settings", { signal: controller.signal })
      .then((value) => {
        if (!controller.signal.aborted) {
          setSetup(value); setGuilds([]); setChannels(undefined); setGuildId(value.selection?.guild_id ?? "");
          setChannelId(value.selection?.channel_id ?? ""); setError("");
        }
      })
      .catch((failure) => { if (!controller.signal.aborted && !onAccessError(failure)) setError(errorMessage(failure)); });
    return () => controller.abort();
  }, [attempt, organizationId, onAccessError]);
  useEffect(() => {
    if (!guildId || (setup?.organization_role && setup.organization_role !== "admin")) return;
    const controller = new AbortController();
    api<{ channels: Choice[] }>(`/settings/channels?guild_id=${encodeURIComponent(guildId)}`, { signal: controller.signal })
      .then((value) => {
        if (!controller.signal.aborted) {
          setChannels(value.channels); setChannelError("");
          setChannelId((current) => value.channels.some((c) => c.id === current) || setup?.organization_role ? current : "");
        }
      })
      .catch((failure) => {
        if (!controller.signal.aborted && !onAccessError(failure)) setChannelError(errorMessage(failure));
      });
    return () => controller.abort();
  }, [guildId, channelAttempt, organizationId, setup?.organization_role, onAccessError]);
  async function refreshServers() {
    setRefreshingServers(true); setError("");
    try {
      const result = await api<{ guilds: Choice[] }>("/settings/guilds");
      setGuilds(result.guilds);
    } catch (failure) { if (!onAccessError(failure)) setError(errorMessage(failure)); }
    finally { setRefreshingServers(false); }
  }
  useEffect(() => {
    if (!setup?.selection) return;
    const controller = new AbortController();
    api<{ guilds: Choice[] }>("/settings/guilds", { signal: controller.signal })
      .then((result) => { if (!controller.signal.aborted) setGuilds(result.guilds); })
      .catch((failure) => { if (!controller.signal.aborted && !onAccessError(failure)) setError(errorMessage(failure)); });
    return () => controller.abort();
  }, [setup?.selection, organizationId, onAccessError]);
  async function save(event: FormEvent) {
    event.preventDefault();
    if (saving || (setup?.organization_role && setup.organization_role !== "admin") || !guildId || !channelId) return;
    setSaving(true); setError("");
    try {
      const selection = await api<Selection>("/settings", { ...mutationOptions(csrf, { guild_id: guildId, channel_id: channelId }), method: "PUT" });
      setSetup((current) => current ? { ...current, selection, disconnected: false } : current);
      await onSaved();
    } catch (failure) { if (!onAccessError(failure)) setError(errorMessage(failure)); }
    finally { setSaving(false); }
  }
  const connectUrl = setup?.connect_url ?? "/api/auth/connect";
  const restricted = Boolean(setup?.organization_role && setup.organization_role !== "admin");
  return <section className="panel settings-panel" aria-labelledby="settings-heading">
    <div className="section-heading"><h2 id="settings-heading">Settings</h2></div>
    <Tabs className="settings-tabs" value={tab} onChange={(_event, value: string) => setTab(value)} aria-label="Settings">
      <Tab label="Discord" value="discord" id={`${tabId}-discord-tab`} aria-controls={`${tabId}-discord-panel`} />
      <Tab label="Assignments" value="assignments" id={`${tabId}-assignments-tab`} aria-controls={`${tabId}-assignments-panel`} />
      <Tab label="Organization" value="organization" id={`${tabId}-organization-tab`} aria-controls={`${tabId}-organization-panel`} />
    </Tabs>
    <div role="tabpanel" id={`${tabId}-discord-panel`} aria-labelledby={`${tabId}-discord-tab`} hidden={tab !== "discord"}>
    {!setup && !error && <p><LoadingIndicator label="Loading settings…" /></p>}
    {error && <p role="alert" className="error">{error}{!setup && <button type="button" onClick={() => setAttempt((n) => n + 1)}>Retry settings</button>}</p>}
    {setup && <>
      <div className="form-actions settings-connections">
        {!setup.selection && <a className="button" href={connectUrl}>Connect</a>}
      </div>
      {setup.selection && <form onSubmit={(event) => void save(event)} aria-label="Discord settings">
        <div className="form-grid">
          <div className="signup-channel-field">
          <FormField label="Discord Server" value={guilds.find((g) => g.id === guildId)?.name ?? setup.selection.guild_name}
            disabled={restricted || saving || guilds.length <= 1} slotProps={{ input: { readOnly: true } }}
            onKeyDown={(event) => { if (!restricted && !saving && guilds.length > 1 && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); setChoosingServer(true); } }}
            onClick={() => { if (!restricted && !saving && guilds.length > 1) setChoosingServer(true); }} />
          <button type="button" className="settings-refresh" aria-label="Refresh Servers" title="Refresh Servers"
            disabled={restricted || saving || refreshingServers} onClick={() => void refreshServers()}><RefreshCw size={18} aria-hidden="true" /></button>
          </div>
          <div className="signup-channel-field">
          {restricted ? <FormField label="Signup Channel" value={`#${setup.selection.channel_name}`} disabled /> : <FormField select label="Signup Channel" value={channels ? channelId : ""} fullWidth disabled={saving || !channels?.length}
            slotProps={{ inputLabel: { shrink: true } }}
            onChange={(event) => setChannelId(event.target.value)}>
            <MenuItem value="">Choose a channel</MenuItem>
            {setup.organization_role && channelId && channels && !channels.some((c) => c.id === channelId) &&
              <MenuItem value={channelId}>#{setup.selection.channel_name}</MenuItem>}
            {(channels ?? []).map((c) => <MenuItem key={c.id} value={c.id}>#{c.name}</MenuItem>)}
          </FormField>}
          {!restricted && <button type="button" className="settings-refresh" aria-label="Refresh Channels" title="Refresh Channels"
            disabled={saving || !guildId || (!channels && !channelError)}
            onClick={() => { setChannelError(""); setChannels(undefined); setChannelAttempt((n) => n + 1); }}>
            <RefreshCw size={18} aria-hidden="true" />
          </button>}
          </div>
        </div>
        {!restricted && guildId && !channels && !channelError && <p><LoadingIndicator label="Loading channels…" /></p>}
        {channelError && <p role="alert" className="error">Could not load channels. {channelError}</p>}
        {!restricted && guildId && <>
          <p className="help">If channels are missing, disconnect from Discord and reconnect.</p>
        </>}
        {channels?.length === 0 && <p className="help">No eligible text channels found.</p>}
        <div className="form-actions"><span title={restricted ? "Only users with admin privileges can save" : undefined}><button className="primary" type="submit" disabled={restricted || saving || !guildId || !channelId || !channels?.some((c) => c.id === channelId)}>{saving ? "Saving…" : "Save"}</button></span>
        {setup.selection && !setup.disconnected && <DisconnectDiscord csrf={csrf} disabled={saving || restricted} onAccessError={onAccessError} onBusyChange={setSaving}
          onDisconnected={async () => {
            await onSaved();
            if (setup.organization_role) { setAttempt((n) => n + 1); return; }
            setSetup((current) => current ? { ...current, selection: null, disconnected: true } : current);
            setGuildId(""); setChannelId(""); setChannels(undefined); setChannelError(""); setError("");
          }} />}
        </div>
      </form>}
      <Dialog open={choosingServer} onClose={() => setChoosingServer(false)} aria-labelledby={`${tabId}-servers-title`} fullWidth maxWidth="xs">
        <DialogTitle id={`${tabId}-servers-title`}>Discord Server</DialogTitle>
        <DialogContent><List>{guilds.map((guild) => <ListItemButton key={guild.id} selected={guild.id === guildId}
          onClick={() => { if (guild.id !== guildId) { setGuildId(guild.id); setChannelId(""); setChannels(undefined); setChannelError(""); } setChoosingServer(false); }}>{guild.name}</ListItemButton>)}</List>
          <button type="button" onClick={() => setChoosingServer(false)}>Close</button>
        </DialogContent>
      </Dialog>
    </>}
    </div>
    <div role="tabpanel" id={`${tabId}-assignments-panel`} aria-labelledby={`${tabId}-assignments-tab`} hidden={tab !== "assignments"}>
      {setup ? <AssignmentSettings key={organizationId ?? `personal:${userId}`} csrf={csrf} restricted={restricted} onAccessError={onAccessError} />
        : <p><LoadingIndicator label="Loading settings…" /></p>}
    </div>
    <div role="tabpanel" id={`${tabId}-organization-panel`} aria-labelledby={`${tabId}-organization-tab`} hidden={tab !== "organization"}>
      {tab === "organization" && <OrganizationSettings csrf={csrf} userId={userId} onSaved={onSaved} onAccessError={onAccessError} />}
    </div>
  </section>;
}
