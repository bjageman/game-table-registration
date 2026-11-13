import { test, expect } from "@playwright/test";

test("uses text Publish and Cancel dismiss controls, and puts assignments in the toolbar", async ({ page }) => {
  let status = "draft";
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    const json = path === "/api/me" ? { username: "organizer", csrf: "csrf" }
      : path === "/api/branding" ? { name: "TableSignup", tagline: "", logo_url: null }
      : path === "/api/events" ? [{ id: "event", title: "Demo Event Time", status, starts_at: 3800000000,
        duration_hours: 24, closes_at: null, discord_url: status === "draft" ? null : "https://discord.com/signup",
        tables: [{ name: "Table A", capacity: 8 }] }]
      : path.endsWith("/signups") ? [{ name: "Table A", players: [], waitlist: [] }]
      : path.endsWith("/announcement") ? { status: "sent", url: "https://discord.com/assignment", error: null } : [];
    return route.fulfill({ json });
  });
  await page.goto("/");
  await page.locator("#event-open-event").click();
  const publish = page.locator("#event-publish-event");
  await expect(publish).toHaveText("Publish");
  await expect(publish.locator("svg")).toHaveCount(0);
  await expect(publish).toHaveAttribute("title", "Publish to Discord");
  await publish.click();
  const confirmation = page.locator("#event-publish-dialog-event");
  await expect(confirmation.getByRole("button", { name: "Close dialog" })).toHaveCount(0);
  await expect(confirmation.getByRole("button", { name: "Cancel" })).toBeFocused();
  await confirmation.getByRole("button", { name: "Cancel" }).click();
  await page.getByRole("button", { name: "Add Player", exact: true }).click();
  const addPlayer = page.locator("#event-add-player-dialog-event");
  await expect(addPlayer.getByRole("button", { name: "Close add player" })).toHaveCount(0);
  await expect(addPlayer.getByText("Type a name or Discord ID to see known players.")).toHaveCount(0);
  await addPlayer.getByRole("button", { name: "Cancel" }).click();
  status = "assigned";
  await page.reload();
  await page.locator("#event-open-event").click();
  const assignment = page.locator(".event-header-actions").getByRole("link", { name: /View Assignment Announcement/ });
  await expect(assignment).toHaveAttribute("href", "https://discord.com/assignment");
  await expect(assignment.locator("svg")).toBeVisible();
  const dimensions = await assignment.boundingBox();
  expect(dimensions?.width).toBe(46);
  expect(dimensions?.height).toBe(46);
});

test("saves the optional open signup roster setting and defaults it off", async ({ page }) => {
  let showPlayers = false;
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/settings/assignment") {
      if (route.request().method() === "PUT") {
        expect(route.request().headers()["x-csrf-token"]).toBe("csrf");
        showPlayers = route.request().postDataJSON().show_open_signup_players;
      }
      return route.fulfill({ json: { automatic_weight_adjustment: true, announce_table_changes: false, post_discord_updates_to_thread: false, timezone: null, show_open_signup_players: showPlayers } });
    }
    const json = path === "/api/me" ? { username: "organizer", csrf: "csrf" }
      : path === "/api/settings" ? { selection: null, connect_url: "/api/auth/connect" }
      : path === "/api/branding" ? { name: "TableSignup", tagline: "", logo_url: null } : [];
    return route.fulfill({ json });
  });
  await page.goto("/#/settings");
  await page.getByRole("tab", { name: "General", exact: true }).click();
  const option = page.getByRole("checkbox", { name: "Show players in open Discord signups" });
  await expect(option).not.toBeChecked();
  await option.check();
  await page.locator("#assignment-settings-save-button").click();
  await expect(page.getByRole("status")).toContainText("settings saved");
  await page.reload();
  await page.getByRole("tab", { name: "General", exact: true }).click();
  await expect(option).toBeChecked();
});
