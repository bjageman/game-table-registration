import { useEffect, useRef, useState } from "react";
import Checkbox from "@mui/material/Checkbox";
import FormControlLabel from "@mui/material/FormControlLabel";
import { api, errorMessage, mutationOptions } from "../../lib/api";
import LoadingIndicator from "../../components/LoadingIndicator";
import { FormField } from "../../components/FormFields";
import { browserTimezone } from "../../lib/timezone";
import { GENERAL_SETTINGS_DEFAULTS, type GeneralSettingsValues } from "../../lib/generalSettings";

export default function GeneralSettings({ csrf, restricted = false, onAccessError, onSaved }: {
  csrf: string; restricted?: boolean; onAccessError: (error: unknown) => boolean; onSaved?: () => Promise<void>;
}) {
  const [settings, setSettings] = useState<GeneralSettingsValues>(GENERAL_SETTINGS_DEFAULTS);
  const [retentionHours, setRetentionHours] = useState(String(GENERAL_SETTINGS_DEFAULTS.waitlist_guarantee_retention_hours));
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const inFlight = useRef(false);
  const timezones = [...new Set(["UTC", ...(Intl.supportedValuesOf?.("timeZone") ?? [browserTimezone()]), ...(settings.timezone ? [settings.timezone] : [])])].sort();

  useEffect(() => {
    const controller = new AbortController();
    api<Partial<GeneralSettingsValues>>("/settings/assignment", { signal: controller.signal }).then((value) => {
      if (!controller.signal.aborted) {
        setSettings({ ...GENERAL_SETTINGS_DEFAULTS, ...value });
        setRetentionHours(String(value.waitlist_guarantee_retention_hours ?? GENERAL_SETTINGS_DEFAULTS.waitlist_guarantee_retention_hours));
        setLoaded(true);
        setError("");
      }
    }).catch((failure) => { if (!controller.signal.aborted && !onAccessError(failure)) setError(errorMessage(failure)); });
    return () => controller.abort();
  }, [attempt, onAccessError]);

  async function updateSettings(patch: Partial<GeneralSettingsValues>) {
    if (inFlight.current || !loaded || restricted) return;
    const previous = settings;
    const next = { ...previous, ...patch };
    inFlight.current = true;
    setBusy(true);
    setSaved(false);
    setError("");
    setSettings(next);
    try {
      const result = await api<GeneralSettingsValues>("/settings/assignment", {
        ...mutationOptions(csrf, next),
        method: "PUT",
      });
      setSettings({ ...GENERAL_SETTINGS_DEFAULTS, ...result });
      await onSaved?.();
      setSaved(true);
    } catch (failure) {
      setSettings(previous);
      setRetentionHours(String(previous.waitlist_guarantee_retention_hours));
      if (!onAccessError(failure)) setError(errorMessage(failure));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  function toggle(field: keyof Omit<GeneralSettingsValues, "timezone" | "waitlist_guarantee_retention_hours">, value: boolean) {
    void updateSettings({ [field]: value });
  }

  function saveRetentionHours() {
    const hours = Number(retentionHours);
    if (!retentionHours.trim() || !Number.isInteger(hours) || hours < 1 || hours > 768) {
      setError("Choose whole hours from 1 to 768.");
      return;
    }
    if (hours !== settings.waitlist_guarantee_retention_hours) {
      void updateSettings({ waitlist_guarantee_retention_hours: hours });
    }
  }

  return <section id="assignment-settings" className="assignment-settings" aria-label="Preferences">
    {!loaded && !error && <p><LoadingIndicator label="Loading preferences…" /></p>}
    {error && <p role="alert" className="error">{error}{!loaded && <button type="button" onClick={() => setAttempt((n) => n + 1)}>Retry</button>}</p>}
    {loaded && <form id="assignment-settings-form" aria-label="Preferences" onSubmit={(event) => event.preventDefault()}>
      <div className="general-timezone-setting">
        <FormField id="general-timezone" select label="Timezone" value={settings.timezone ?? ""} disabled={busy || restricted}
          slotProps={{ select: { native: true } }}
          onChange={(event) => void updateSettings({ timezone: event.target.value || null })}>
          <option value="">Default ({browserTimezone()})</option>
          {timezones.map((zone) => <option key={zone} value={zone}>{zone.replaceAll("_", " ")}</option>)}
        </FormField>
      </div>
      <section className="settings-group" aria-labelledby="player-management-heading">
        <h3 id="player-management-heading">Player Management</h3>
        <div className="general-setting-option"><FormControlLabel label="Automatically Adjust Player Weights" control={<Checkbox id="assignment-auto-weights" checked={settings.automatic_weight_adjustment} disabled={busy || restricted}
          onChange={(event) => toggle("automatic_weight_adjustment", event.target.checked)} />} /></div>
        <div className="general-setting-option">
          <FormControlLabel label="Waitlisted players will be guaranteed a seat for the next event" control={<Checkbox id="general-guarantee-waitlisted" checked={settings.guarantee_waitlisted_players} disabled={busy || restricted}
            onChange={(event) => toggle("guarantee_waitlisted_players", event.target.checked)} />} />
          {settings.guarantee_waitlisted_players && <div className="short-notice-setting">
            <FormControlLabel label="Player keeps the guarantee if placed on short notice" control={<Checkbox id="general-keep-short-notice-guarantee" checked={settings.keep_waitlist_guarantee_on_short_notice} disabled={busy || restricted}
              onChange={(event) => toggle("keep_waitlist_guarantee_on_short_notice", event.target.checked)} />} />
            <FormField id="general-guarantee-retention-hours" label="Hours before event" type="number" value={retentionHours} className="short-notice-hours" fullWidth={false}
              disabled={busy || restricted || !settings.keep_waitlist_guarantee_on_short_notice}
              slotProps={{ htmlInput: { min: 1, max: 768, step: 1 } }}
              onChange={(event) => setRetentionHours(event.target.value)} onBlur={saveRetentionHours}
              onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); saveRetentionHours(); } }} />
          </div>}
        </div>
      </section>
      <section className="settings-group" aria-labelledby="discord-preferences-heading">
        <h3 id="discord-preferences-heading">Discord</h3>
        <div className="general-setting-option"><FormControlLabel label="Create an event when a signup is published" control={<Checkbox id="general-create-discord-event" checked={settings.create_discord_event} disabled={busy || restricted}
          onChange={(event) => toggle("create_discord_event", event.target.checked)} />} /></div>
        <div className="general-setting-option"><FormControlLabel label="Review assignments before sending" control={<Checkbox id="general-review-assignments" checked={settings.review_assignments_before_discord} disabled={busy || restricted}
          onChange={(event) => toggle("review_assignments_before_discord", event.target.checked)} />} /></div>
        <div className="general-setting-option"><FormControlLabel label="Announce table changes" control={<Checkbox id="assignment-announce-changes" checked={settings.announce_table_changes} disabled={busy || restricted}
          onChange={(event) => toggle("announce_table_changes", event.target.checked)} />} /></div>
        <div className="general-setting-option"><FormControlLabel label="Post updates to a new thread" control={<Checkbox id="assignment-thread-updates" checked={settings.post_discord_updates_to_thread} disabled={busy || restricted}
          onChange={(event) => toggle("post_discord_updates_to_thread", event.target.checked)} />} /></div>
        <div className="general-setting-option"><FormControlLabel label="Show players in open signups" control={<Checkbox id="general-show-signup-players" checked={settings.show_open_signup_players} disabled={busy || restricted}
          onChange={(event) => toggle("show_open_signup_players", event.target.checked)} />} /></div>
        <div className="general-setting-option"><FormControlLabel label="Send private messages for waitlist promotions" control={<Checkbox id="general-dm-waitlist-promotions" checked={settings.dm_waitlist_promotions} disabled={busy || restricted}
          onChange={(event) => toggle("dm_waitlist_promotions", event.target.checked)} />} /></div>
        <div className="general-setting-option"><FormControlLabel label="Send private messages for table assignments" control={<Checkbox id="general-dm-assignments" checked={settings.dm_assignments} disabled={busy || restricted}
          onChange={(event) => toggle("dm_assignments", event.target.checked)} />} /></div>
      </section>
      {busy && <p role="status">Saving…</p>}
      {saved && <p role="status">Settings saved.</p>}
    </form>}
  </section>;
}
