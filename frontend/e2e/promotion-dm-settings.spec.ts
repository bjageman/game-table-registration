import { test, expect } from "./fixtures";

test("private waitlist notifications are opt-in, independent, and persist", async ({ page }) => {
  let enabled = false;
  await page.route("**/api/me", route => route.fulfill({ json: { username: "organizer", csrf: "csrf" } }));
  await page.route("**/api/settings", route => route.fulfill({ json: { selection: null, connect_url: "/api/auth/connect" } }));
  await page.route("**/api/settings/assignment", route => {
    if (route.request().method() === "PUT") {
      expect(route.request().headers()["x-csrf-token"]).toBe("csrf");
      const body = route.request().postDataJSON();
      enabled = body.dm_waitlist_promotions;
      expect(body.announce_table_changes).toBe(false);
    }
    return route.fulfill({ json: {
      automatic_weight_adjustment: true, announce_table_changes: false,
      post_discord_updates_to_thread: false, show_open_signup_players: false,
      timezone: null, dm_waitlist_promotions: enabled,
    } });
  });
  await page.goto("/#/settings");
  await page.getByRole("tab", { name: "General", exact: true }).click();
  const option = page.getByRole("checkbox", { name: "Send private messages for waitlist promotions" });
  await expect(option).not.toBeChecked();
  await option.check();
  await page.locator("#assignment-settings-save-button").click();
  await expect(page.getByRole("status")).toHaveText("Assignment settings saved.");
  await page.reload();
  await page.getByRole("tab", { name: "General", exact: true }).click();
  await expect(option).toBeChecked();
  await option.uncheck();
  await page.locator("#assignment-settings-save-button").click();
  await expect(page.getByRole("status")).toHaveText("Assignment settings saved.");
  expect(enabled).toBe(false);
});
