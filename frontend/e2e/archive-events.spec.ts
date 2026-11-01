import { test, expect } from "@playwright/test";

test("archives only after confirmation and keeps saved placements available", async ({ page }) => {
  let archives = 0;
  const event = { id: "event", title: "Game Night", status: "assigned", starts_at: 3800000000,
    duration_hours: 24, closes_at: 3799900000, discord_url: "https://discord.com/poll",
    archived_at: null as number | null, tables: [{ name: "Table A", capacity: 1 }] };
  await page.route("**/api/me", (route) => route.fulfill({ json: { username: "organizer", csrf: "csrf" } }));
  await page.route("**/api/events", (route) => route.fulfill({ json: [event] }));
  await page.route("**/api/events/event/signups", (route) => route.fulfill({ json: [{ name: "Table A", players: [{ id: "1", name: "Mary" }], waitlist: [{ id: "2", name: "Dan" }] }] }));
  await page.route("**/api/events/event/announcement", (route) => route.fulfill({ json: { status: "sent", error: null, url: "https://discord.com/announcement" } }));
  await page.route("**/api/events/event/archive", (route) => {
    expect(route.request().method()).toBe("POST");
    expect(route.request().headers()["x-csrf-token"]).toBe("csrf");
    archives++; event.archived_at = 3800000000;
    return route.fulfill({ json: event });
  });
  await page.goto("/");
  await page.getByRole("button", { name: /^Game Night/ }).click();
  const details = page.getByRole("dialog", { name: "Game Night", exact: true });
  await details.getByRole("button", { name: "Archive event", exact: true }).click();
  const confirmation = page.getByRole("dialog", { name: "Archive Game Night?" });
  await confirmation.getByRole("button", { name: "Cancel", exact: true }).click();
  expect(archives).toBe(0);
  await details.getByRole("button", { name: "Archive event", exact: true }).click();
  await confirmation.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(details).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^Game Night/ })).toHaveCount(0);
  await page.getByLabel("Show Archived").check();
  await page.getByRole("button", { name: /^Game Night Archived/ }).click();
  await expect(details.locator(".table-players").getByRole("button", { name: "Mary" })).toBeVisible();
  await expect(details.locator(".table-waitlist").getByRole("button", { name: "Dan" })).toBeVisible();
  await expect(details.getByRole("button", { name: "Archive event", exact: true })).toHaveCount(0);
  expect(archives).toBe(1);
  await page.reload();
  await expect(page.getByRole("button", { name: /^Game Night/ })).toHaveCount(0);
  await page.getByLabel("Show Archived").check();
  await expect(page.getByRole("button", { name: /^Game Night Archived/ })).toBeVisible();
});
