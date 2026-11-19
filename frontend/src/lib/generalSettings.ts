/** General Settings uses the existing /settings/assignment API. */
export interface GeneralSettingsValues {
  create_discord_event: boolean;
  review_assignments_before_discord: boolean;
  automatic_weight_adjustment: boolean;
  announce_table_changes: boolean;
  post_discord_updates_to_thread: boolean;
  timezone: string | null;
  show_open_signup_players: boolean;
  dm_waitlist_promotions: boolean;
  dm_assignments: boolean;
  guarantee_waitlisted_players: boolean;
  waitlist_guarantee_retention_hours: number;
  keep_waitlist_guarantee_on_short_notice: boolean;
}

export const GENERAL_SETTINGS_DEFAULTS: GeneralSettingsValues = {
  create_discord_event: true,
  review_assignments_before_discord: true,
  automatic_weight_adjustment: true,
  announce_table_changes: true,
  post_discord_updates_to_thread: true,
  timezone: null,
  show_open_signup_players: true,
  dm_waitlist_promotions: true,
  dm_assignments: true,
  guarantee_waitlisted_players: false,
  waitlist_guarantee_retention_hours: 5,
  keep_waitlist_guarantee_on_short_notice: true,
};
