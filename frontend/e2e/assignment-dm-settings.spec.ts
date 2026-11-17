import { test, expect } from "./fixtures";

test("assignment PM setting persists and player preference stays visible when it is off", async ({ page }) => {
  let enabled = true;
  let receive = true;
  await page.route("**/api/me", route => route.fulfill({ json: { username: "organizer", csrf: "csrf" } }));
  await page.route("**/api/settings", route => route.fulfill({ json: { selection: null, connect_url: "/api/auth/connect" } }));
  await page.route("**/api/settings/assignment", route => {
    if (route.request().method() === "PUT") enabled = route.request().postDataJSON().dm_assignments;
    return route.fulfill({ json: { automatic_weight_adjustment: true, announce_table_changes: false,
      dm_assignments: enabled, dm_waitlist_promotions: false } });
  });
  await page.route("**/api/events", route => route.fulfill({ json: [{
    id: "event", title: "Games", status: "open", starts_at: 3800000000,
    duration_hours: 24, closes_at: 3799900000, discord_url: null,
    tables: [{ name: "A", capacity: 5 }],
  }] }));
  await page.route("**/api/events/event/signups", route => route.fulfill({ json: [{ name: "A", players: [{ id: "123", name: "Mary" }] }] }));
  await page.route("**/api/players/123*", route => {
    if (route.request().method() === "PUT") {
      expect(route.request().postDataJSON()).toEqual({ seat_notifications: false });
      expect(route.request().headers()["x-csrf-token"]).toBe("csrf");
      receive = route.request().postDataJSON().seat_notifications;
    }
    return route.fulfill({ json: { discord_id: "123", discord_name: "Mary", real_name: "", weighting: 5,
      guaranteed_seat: false, seat_notifications: receive } });
  });
  await page.goto("/#/settings");
  await page.getByRole("tab", { name: "Preferences", exact: true }).click();
  const organization = page.getByRole("checkbox", { name: "Send private messages for table assignments" });
  await expect(organization).toBeChecked();
  await organization.click();
  await expect(page.getByRole("status")).toHaveText("Settings saved.");
  await page.reload();
  await page.getByRole("tab", { name: "Preferences", exact: true }).click();
  await expect(organization).not.toBeChecked();
  await page.goto("/");
  await page.locator("#event-open-event").click();
  await page.getByRole("button", { name: "Mary", exact: true }).click();
  const player = page.getByRole("checkbox", { name: "Private Notifications" });
  await expect(player).toBeVisible();
  await expect(player).toBeEnabled();
  await player.click();
  await expect(player).not.toBeChecked();
  await expect.poll(() => receive).toBe(false);
  await page.getByRole("button", { name: "Close player information" }).click();
  await page.getByRole("button", { name: "Mary", exact: true }).click();
  await expect(player).not.toBeChecked();
});
