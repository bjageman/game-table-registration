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
