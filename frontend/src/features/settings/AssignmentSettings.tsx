import { useEffect, useRef, useState, type FormEvent } from "react";
import Checkbox from "@mui/material/Checkbox";
import FormControlLabel from "@mui/material/FormControlLabel";
import { api, errorMessage, mutationOptions } from "../../lib/api";
import LoadingIndicator from "../../components/LoadingIndicator";
import { FormField } from "../../components/FormFields";
import { browserTimezone } from "../../lib/timezone";

interface Settings { review_assignments_before_discord?: boolean; automatic_weight_adjustment: boolean; announce_table_changes: boolean; post_discord_updates_to_thread: boolean; timezone?: string | null; show_open_signup_players?: boolean; dm_waitlist_promotions?: boolean; }

export default function AssignmentSettings({ csrf, restricted = false, onAccessError, onSaved }: {
  csrf: string; restricted?: boolean; onAccessError: (error: unknown) => boolean; onSaved?: () => Promise<void>;
}) {
  const [reviewAssignments, setReviewAssignments] = useState(true);
  const [enabled, setEnabled] = useState(true);
  const [announceChanges, setAnnounceChanges] = useState(true);
  const [threadUpdates, setThreadUpdates] = useState(true);
  const [showSignupPlayers, setShowSignupPlayers] = useState(true);
  const [dmPromotions, setDmPromotions] = useState(true);
  const [timezone, setTimezone] = useState("");
  const timezones = [...new Set(["UTC", ...(Intl.supportedValuesOf?.("timeZone") ?? [browserTimezone()]), ...(timezone ? [timezone] : [])])].sort();
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const inFlight = useRef(false);
  useEffect(() => {
    const controller = new AbortController();
    api<Settings>("/settings/assignment", { signal: controller.signal }).then((value) => {
      if (!controller.signal.aborted) { setReviewAssignments(value.review_assignments_before_discord ?? true); setEnabled(value.automatic_weight_adjustment); setAnnounceChanges(value.announce_table_changes); setThreadUpdates(value.post_discord_updates_to_thread ?? true); setTimezone(value.timezone ?? ""); setShowSignupPlayers(value.show_open_signup_players ?? true); setDmPromotions(value.dm_waitlist_promotions ?? true); setLoaded(true); setError(""); }
    }).catch((failure) => { if (!controller.signal.aborted && !onAccessError(failure)) setError(errorMessage(failure)); });
    return () => controller.abort();
  }, [attempt, onAccessError]);
  async function save(event: FormEvent) {
    event.preventDefault();
    if (inFlight.current || !loaded || restricted) return;
    inFlight.current = true; setBusy(true); setSaved(false); setError("");
    try {
      const result = await api<Settings>("/settings/assignment", { ...mutationOptions(csrf, { review_assignments_before_discord: reviewAssignments, automatic_weight_adjustment: enabled, announce_table_changes: announceChanges, post_discord_updates_to_thread: threadUpdates, timezone: timezone || null, show_open_signup_players: showSignupPlayers, dm_waitlist_promotions: dmPromotions }), method: "PUT" });
      setReviewAssignments(result.review_assignments_before_discord ?? true); setEnabled(result.automatic_weight_adjustment); setAnnounceChanges(result.announce_table_changes); setThreadUpdates(result.post_discord_updates_to_thread ?? true); setTimezone(result.timezone ?? ""); setShowSignupPlayers(result.show_open_signup_players ?? true); setDmPromotions(result.dm_waitlist_promotions ?? true); await onSaved?.(); setSaved(true);
    } catch (failure) { if (!onAccessError(failure)) setError(errorMessage(failure)); }
    finally { inFlight.current = false; setBusy(false); }
  }
  return <section id="assignment-settings" className="assignment-settings" aria-label="Assignment settings">
    {!loaded && !error && <p><LoadingIndicator label="Loading assignment settings…" /></p>}
    {error && <p role="alert" className="error">{error}{!loaded && <button type="button" onClick={() => setAttempt((n) => n + 1)}>Retry</button>}</p>}
    {loaded && <form id="assignment-settings-form" aria-label="Assignment settings" onSubmit={(event) => void save(event)}>
      <div className="general-setting-option"><FormControlLabel label="Review assignments before sending to Discord" control={<Checkbox id="general-review-assignments" checked={reviewAssignments} disabled={busy || restricted}
        onChange={(event) => { setReviewAssignments(event.target.checked); setSaved(false); }} />} /></div>
      <div className="general-setting-option"><FormControlLabel label="Automatically Adjust Player Weights" control={<Checkbox id="assignment-auto-weights" checked={enabled} disabled={busy || restricted}
        onChange={(event) => { setEnabled(event.target.checked); setSaved(false); }} />} /></div>
      <div className="general-setting-option"><FormControlLabel label="Announce Table Changes on Discord" control={<Checkbox id="assignment-announce-changes" checked={announceChanges} disabled={busy || restricted}
        onChange={(event) => { setAnnounceChanges(event.target.checked); setSaved(false); }} />} /></div>
      <div className="general-setting-option"><FormControlLabel label="Post Discord updates to a new thread" control={<Checkbox id="assignment-thread-updates" checked={threadUpdates} disabled={busy || restricted}
        onChange={(event) => { setThreadUpdates(event.target.checked); setSaved(false); }} />} /></div>
      <div className="general-setting-option"><FormControlLabel label="Show players in open Discord signups" control={<Checkbox id="general-show-signup-players" checked={showSignupPlayers} disabled={busy || restricted}
        onChange={(event) => { setShowSignupPlayers(event.target.checked); setSaved(false); }} />} /></div>
      <div className="general-setting-option"><FormControlLabel label="Send private messages for waitlist promotions" control={<Checkbox id="general-dm-waitlist-promotions" checked={dmPromotions} disabled={busy || restricted}
        onChange={(event) => { setDmPromotions(event.target.checked); setSaved(false); }} />} /></div>
      <div className="general-setting-option general-timezone-setting">
        <FormField id="general-timezone" select label="Timezone" value={timezone} disabled={busy || restricted}
          slotProps={{ select: { native: true } }}
          onChange={(event) => { setTimezone(event.target.value); setSaved(false); }}>
          <option value="">Default ({browserTimezone()})</option>
          {timezones.map((zone) => <option key={zone} value={zone}>{zone.replaceAll("_", " ")}</option>)}
        </FormField>
      </div>
      {saved && <p role="status">Assignment settings saved.</p>}
      <div className="form-actions"><span title={restricted ? "Only users with admin privileges can save" : undefined}><button id="assignment-settings-save-button" type="submit" className="primary" disabled={busy || restricted}>{busy ? "Saving…" : "Save"}</button></span></div>
    </form>}
  </section>;
}
