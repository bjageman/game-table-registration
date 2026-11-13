import { test, expect } from "./fixtures";

test("adds a known player after assignment and keeps failed additions available to retry", async ({ page }) => {
  let attempts = 0;
  let added = false;
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/events/event/manager-players/123") {
      expect(route.request().method()).toBe("PUT");
      expect(route.request().headers()["x-csrf-token"]).toBe("csrf");
      expect(route.request().postDataJSON()).toEqual({ table: "Table A", name: "mary" });
      if (++attempts === 1) return route.fulfill({ status: 409, json: { detail: "Please retry" } });
      added = true;
      return route.fulfill({ json: { ok: true } });
    }
    const json = path === "/api/me" ? { username: "organizer", csrf: "csrf" }
      : path === "/api/branding" ? { name: "TableSignup", tagline: "", logo_url: null }
      : path === "/api/events" ? [{ id: "event", title: "Assigned Event", status: "assigned", starts_at: 3800000000,
        duration_hours: 24, closes_at: 3799900000, discord_url: "https://discord.com/poll",
        tables: [{ name: "Table A", capacity: 1 }] }]
      : path.endsWith("/signups") ? [{ name: "Table A", players: [{ id: "456", name: "dan" }, ...(added ? [{ id: "123", name: "mary" }] : [])], waitlist: [] }]
      : path === "/api/players" ? [{ discord_id: "123", discord_name: "mary", real_name: "Mary Jones" }, { discord_id: "456", discord_name: "dan", real_name: "Daniel" }]
      : path.endsWith("/announcement") ? { status: "sent", error: null, url: "https://discord.com/announcement" } : [];
    return route.fulfill({ json });
  });
  await page.goto("/");
  await page.locator("#event-open-event").click();
  await expect(page.getByRole("button", { name: "dan", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Add Player", exact: true }).click();
  const dialog = page.locator("#event-add-player-dialog-event");
  await dialog.getByRole("combobox", { name: "Search players" }).fill("dan");
  await expect(dialog.getByText(/No known players match/)).toBeVisible();
  await dialog.getByRole("combobox", { name: "Search players" }).fill("mar");
  await dialog.getByRole("button", { name: /Mary Jones/ }).click();
  await expect(dialog.getByRole("alert")).toHaveText("Please retry");
  await dialog.getByRole("button", { name: /Mary Jones/ }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole("button", { name: "mary", exact: true })).toBeVisible();
  await expect(page.getByText("2/1", { exact: true })).toBeVisible();
});
