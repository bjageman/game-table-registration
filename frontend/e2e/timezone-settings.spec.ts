import { test, expect } from "./fixtures";

test("saves the timezone and keeps all three event timestamps on single lines", async ({ page }) => {
  let timezone: string | null = "America/New_York";
  const starts = Date.parse("2090-01-15T19:00:00Z") / 1000;
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/settings/assignment") {
      if (route.request().method() === "PUT") {
        expect(route.request().headers()["x-csrf-token"]).toBe("csrf");
        timezone = route.request().postDataJSON().timezone;
      }
      return route.fulfill({ json: { automatic_weight_adjustment: true, announce_table_changes: false, post_discord_updates_to_thread: false, timezone } });
    }
    const json = path === "/api/me" ? { username: "organizer", csrf: "csrf", timezone }
      : path === "/api/branding" ? { name: "TableSignup", tagline: "", logo_url: null }
      : path === "/api/events" ? [{ id: "event", title: "Timezone Event", status: "open", starts_at: starts,
        published_at: starts - 48 * 3600, duration_hours: 24, closes_at: starts - 24 * 3600,
        discord_url: "https://discord.com/poll", tables: [{ name: "Table A", capacity: 8 }] }]
      : path === "/api/settings" ? { selection: null, connect_url: "/api/auth/connect" }
      : path.endsWith("/signups") ? [{ name: "Table A", players: [] }] : [];
    return route.fulfill({ json });
  });
  await page.goto("/");
  await page.locator("#event-open-event").click();
  const rows = page.locator(".event-date-line");
  await expect(rows).toHaveCount(3);
  await expect(rows.first().locator("time")).toContainText("2:00");
  for (const width of [320, 412, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await expect.poll(() => rows.evaluateAll((elements) => elements.every((row) => {
      const time = row.querySelector("time")!;
      const label = row.querySelector("dt")!.getBoundingClientRect();
      const value = row.querySelector("dd")!.getBoundingClientRect();
      const bounds = row.getBoundingClientRect();
      const range = document.createRange();
      range.selectNodeContents(time);
      if (window.innerWidth > 600) return label.bottom <= value.top && getComputedStyle(row).fontSize === "16px";
      return row.scrollWidth <= row.clientWidth + 1 && range.getClientRects().length === 1
        && Math.abs(label.left - bounds.left) < 1 && Math.abs(value.right - bounds.right) < 1
        && label.right + 5 <= value.left;
    }))).toBe(true);
    const fontSizes = await rows.evaluateAll((elements) => elements.map((row) => getComputedStyle(row).fontSize));
    expect(new Set(fontSizes).size).toBe(1);
    await expect(rows).not.toContainText(["EST", "EDT", "EST"]);
  }
  await page.locator("#event-close-event").click();
  await page.goto("/#/settings");
  await page.getByRole("tab", { name: "General", exact: true }).click();
  await page.locator("#general-timezone").selectOption("America/Los_Angeles");
  await expect(page.getByRole("status")).toHaveText("Settings saved.");
  await page.locator("#home-link").click();
  await page.locator("#event-open-event").click();
  await expect(page.locator(".event-date-line").first().locator("time")).toContainText("11:00");
  await page.locator("#event-close-event").click();
  await page.locator("#event-create-button").click();
  await expect(page.locator("#event-form")).toBeVisible();
  expect(errors).toEqual([]);
});
