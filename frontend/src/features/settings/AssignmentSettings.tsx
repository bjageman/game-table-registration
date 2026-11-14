import { useEffect, useRef, useState } from "react";
import Checkbox from "@mui/material/Checkbox";
import FormControlLabel from "@mui/material/FormControlLabel";
import { api, errorMessage, mutationOptions } from "../../lib/api";
import LoadingIndicator from "../../components/LoadingIndicator";
import { FormField } from "../../components/FormFields";
import { browserTimezone } from "../../lib/timezone";

interface Settings {
  review_assignments_before_discord: boolean;
  automatic_weight_adjustment: boolean;
  announce_table_changes: boolean;
  post_discord_updates_to_thread: boolean;
  timezone: string | null;
  show_open_signup_players: boolean;
  dm_waitlist_promotions: boolean;
}

const DEFAULTS: Settings = {
  review_assignments_before_discord: true,
  automatic_weight_adjustment: true,
  announce_table_changes: true,
  post_discord_updates_to_thread: true,
  timezone: null,
  show_open_signup_players: true,
  dm_waitlist_promotions: true,
};

export default function AssignmentSettings({ csrf, restricted = false, onAccessError, onSaved }: {
  csrf: string; restricted?: boolean; onAccessError: (error: unknown) => boolean; onSaved?: () => Promise<void>;
}) {
  const [settings, setSettings] = useState<Settings>(DEFAULTS);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const inFlight = useRef(false);
  const timezones = [...new Set(["UTC", ...(Intl.supportedValuesOf?.("timeZone") ?? [browserTimezone()]), ...(settings.timezone ? [settings.timezone] : [])])].sort();

  useEffect(() => {
    const controller = new AbortController();
    api<Partial<Settings>>("/settings/assignment", { signal: controller.signal }).then((value) => {
      if (!controller.signal.aborted) {
        setSettings({ ...DEFAULTS, ...value });
        setLoaded(true);
        setError("");
      }
    }).catch((failure) => { if (!controller.signal.aborted && !onAccessError(failure)) setError(errorMessage(failure)); });
    return () => controller.abort();
  }, [attempt, onAccessError]);

  async function updateSettings(patch: Partial<Settings>) {
    if (inFlight.current || !loaded || restricted) return;
    const previous = settings;
    const next = { ...previous, ...patch };
    inFlight.current = true;
    setBusy(true);
    setSaved(false);
    setError("");
    setSettings(next);
    try {
      const result = await api<Settings>("/settings/assignment", {
        ...mutationOptions(csrf, next),
        method: "PUT",
      });
      setSettings({ ...DEFAULTS, ...result });
      await onSaved?.();
      setSaved(true);
    } catch (failure) {
      setSettings(previous);
      if (!onAccessError(failure)) setError(errorMessage(failure));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  function toggle(field: keyof Omit<Settings, "timezone">, value: boolean) {
    void updateSettings({ [field]: value });
  }

  return <section id="assignment-settings" className="assignment-settings" aria-label="Assignment settings">
    {!loaded && !error && <p><LoadingIndicator label="Loading assignment settings…" /></p>}
    {error && <p role="alert" className="error">{error}{!loaded && <button type="button" onClick={() => setAttempt((n) => n + 1)}>Retry</button>}</p>}
    {loaded && <form id="assignment-settings-form" aria-label="Assignment settings" onSubmit={(event) => event.preventDefault()}>
      <div className="general-setting-option"><FormControlLabel label="Review assignments before sending to Discord" control={<Checkbox id="general-review-assignments" checked={settings.review_assignments_before_discord} disabled={busy || restricted}
        onChange={(event) => toggle("review_assignments_before_discord", event.target.checked)} />} /></div>
      <div className="general-setting-option"><FormControlLabel label="Automatically Adjust Player Weights" control={<Checkbox id="assignment-auto-weights" checked={settings.automatic_weight_adjustment} disabled={busy || restricted}
        onChange={(event) => toggle("automatic_weight_adjustment", event.target.checked)} />} /></div>
      <div className="general-setting-option"><FormControlLabel label="Announce Table Changes on Discord" control={<Checkbox id="assignment-announce-changes" checked={settings.announce_table_changes} disabled={busy || restricted}
        onChange={(event) => toggle("announce_table_changes", event.target.checked)} />} /></div>
      <div className="general-setting-option"><FormControlLabel label="Post Discord updates to a new thread" control={<Checkbox id="assignment-thread-updates" checked={settings.post_discord_updates_to_thread} disabled={busy || restricted}
        onChange={(event) => toggle("post_discord_updates_to_thread", event.target.checked)} />} /></div>
      <div className="general-setting-option"><FormControlLabel label="Show players in open Discord signups" control={<Checkbox id="general-show-signup-players" checked={settings.show_open_signup_players} disabled={busy || restricted}
        onChange={(event) => toggle("show_open_signup_players", event.target.checked)} />} /></div>
      <div className="general-setting-option"><FormControlLabel label="Send private messages for waitlist promotions" control={<Checkbox id="general-dm-waitlist-promotions" checked={settings.dm_waitlist_promotions} disabled={busy || restricted}
        onChange={(event) => toggle("dm_waitlist_promotions", event.target.checked)} />} /></div>
      <div className="general-setting-option general-timezone-setting">
        <FormField id="general-timezone" select label="Timezone" value={settings.timezone ?? ""} disabled={busy || restricted}
          slotProps={{ select: { native: true } }}
          onChange={(event) => void updateSettings({ timezone: event.target.value || null })}>
          <option value="">Default ({browserTimezone()})</option>
          {timezones.map((zone) => <option key={zone} value={zone}>{zone.replaceAll("_", " ")}</option>)}
        </FormField>
      </div>
      {busy && <p role="status">Saving…</p>}
      {saved && <p role="status">Settings saved.</p>}
    </form>}
  </section>;
}
