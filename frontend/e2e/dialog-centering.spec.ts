import { test, expect } from "@playwright/test";

test("centers the event details modal in the viewport", async ({ page }) => {
  await page.route("**/api/me", (route) => route.fulfill({ json: { username: "organizer", csrf: "csrf" } }));
  await page.route("**/api/events", (route) => route.fulfill({ json: [{
    id: "event", title: "Game Night", status: "open", starts_at: 3800000000,
    duration_hours: 24, closes_at: 3799900000, discord_url: "https://discord.com/poll",
    tables: [{ name: "Table A", capacity: 8 }],
  }] }));
  await page.route("**/api/events/event/signups", (route) => route.fulfill({ json: [{ name: "Table A", players: [] }] }));
  await page.goto("/");
  await page.getByRole("button", { name: /^Game Night/ }).click();
  const dialog = page.getByRole("dialog", { name: "Game Night", exact: true });
  await expect(dialog).toBeVisible();
  const bounds = await dialog.boundingBox();
  const viewport = page.viewportSize();
  expect(bounds).not.toBeNull();
  expect(viewport).not.toBeNull();
  expect(Math.abs(bounds!.x + bounds!.width / 2 - viewport!.width / 2)).toBeLessThan(2);
  expect(Math.abs(bounds!.y + bounds!.height / 2 - viewport!.height / 2)).toBeLessThan(2);
});
