import { test, expect } from "@playwright/test";

test("edits a persistent player profile inside the event modal", async ({ page }) => {
  let realName = "";
  const event = { id: "event", title: "Game Night", status: "open", starts_at: 3800000000,
    duration_hours: 24, closes_at: 3799900000, discord_url: "https://discord.com/poll",
    tables: [{ name: "Table A", capacity: 8 }] };
  await page.route("**/api/me", (route) => route.fulfill({ json: { username: "organizer", csrf: "csrf" } }));
  await page.route("**/api/events", (route) => route.fulfill({ json: [event] }));
  await page.route("**/api/events/event/signups", (route) => route.fulfill({ json: [{ name: "Table A", players: [{ id: "123", name: "Mary" }] }] }));
  await page.route("**/api/players/123", async (route) => {
    if (route.request().method() === "PUT") {
      expect(route.request().headers()["x-csrf-token"]).toBe("csrf");
      realName = route.request().postDataJSON().real_name;
    }
    await route.fulfill({ json: { discord_id: "123", discord_name: "Mary", real_name: realName, weighting: 1.0 } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: /Game Night open 1 table/ }).click();
  await page.getByRole("button", { name: "Mary", exact: true }).click();
  const profile = page.getByRole("dialog", { name: "Player Information" });
  await expect(profile).toBeVisible();
  await expect(profile.getByText("Mary", { exact: true })).toBeVisible();
  await expect(profile.getByText("1.0", { exact: true })).toBeVisible();
  await profile.getByLabel("Real Name", { exact: true }).fill("Mary Smith");
  await profile.getByRole("button", { name: "Save", exact: true }).click();
  await expect(profile.getByRole("status")).toHaveText("Player information saved.");
  await profile.getByRole("button", { name: "Close player information" }).click();
  await expect(page.getByRole("dialog", { name: "Game Night", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Mary", exact: true }).click();
  await expect(profile.getByLabel("Real Name", { exact: true })).toHaveValue("Mary Smith");
});

test("test profile fields have space for labels and guarantees use selected tables", async ({ page }, testInfo) => {
  const event = { id: "event", title: "Game Night", status: "open", starts_at: 3800000000,
    duration_hours: 24, closes_at: 3799900000, discord_url: "https://discord.com/poll", is_test: true,
    tables: [{ name: "Table A", capacity: 8 }] };
  const saved = { discord_id: "test-123", discord_name: "Test Player 001", real_name: "", weighting: 1, is_test: true, guaranteed_seat: false };
  await page.route("**/api/me", (route) => route.fulfill({ json: { username: "organizer", csrf: "csrf" } }));
  await page.route("**/api/events", (route) => route.fulfill({ json: [event] }));
  await page.route("**/api/events/event/signups", (route) => route.fulfill({ json: [{ name: "Table A", players: [{ id: saved.discord_id, name: saved.discord_name }] }] }));
  await page.route("**/api/players/test-123", async (route) => {
    if (route.request().method() === "PUT") Object.assign(saved, route.request().postDataJSON());
    await route.fulfill({ json: saved });
  });
  await page.goto("/");
  await page.getByRole("button", { name: /^Game Night/ }).click();
  await page.getByRole("button", { name: "Test Player 001", exact: true }).click();
  const profile = page.getByRole("dialog", { name: "Player Information" });
  await expect(profile.getByLabel("Current Weighting")).toBeVisible();
  const name = await profile.getByLabel("Real Name").locator("..").boundingBox();
  const weight = await profile.getByLabel("Current Weighting").locator("..").boundingBox();
  const weightLabel = await profile.locator("label", { hasText: "Current Weighting" }).boundingBox();
  expect(name).not.toBeNull(); expect(weight).not.toBeNull(); expect(weightLabel).not.toBeNull();
  expect(weight!.y - (name!.y + name!.height)).toBeGreaterThanOrEqual(23);
  expect(weightLabel!.y - (name!.y + name!.height)).toBeGreaterThan(8);
  expect(Math.abs(weight!.x - name!.x)).toBeLessThan(1);
  expect(Math.abs(weight!.width - name!.width)).toBeLessThan(1);
  await profile.getByLabel("Guaranteed Seat").check();
  await expect(profile.getByLabel("Reserved Table")).toHaveCount(0);
  await profile.screenshot({ path: `/tmp/tablesignup-profile-spacing-${testInfo.project.name}.png` });
  await profile.getByLabel("Real Name").fill("Volunteer");
  await profile.getByLabel("Current Weighting").fill("2.5");
  await profile.getByRole("button", { name: "Save", exact: true }).click();
  await expect(profile.getByRole("status")).toHaveText("Player information saved.");
  expect(saved.guaranteed_seat).toBe(true);
  expect(saved.weighting).toBe(2.5);
});
