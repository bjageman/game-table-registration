import { test, expect } from "@playwright/test";

test("confirms closing signups and shows saved placements and waitlists", async ({ page }) => {
  let closed = false;
  let closures = 0;
  const event = { id: "event", title: "Game Night", status: "open", starts_at: 3800000000,
    duration_hours: 24, closes_at: 3799900000, published_at: 3799813600,
    discord_url: "https://discord.com/poll", tables: [{ name: "Table A", capacity: 1 }] };
  await page.route("**/api/me", (route) => route.fulfill({ json: { username: "organizer", csrf: "csrf" } }));
  await page.route("**/api/events", (route) => route.fulfill({ json: [event] }));
  await page.route("**/api/events/event/signups", (route) => route.fulfill({ json: [{
    name: "Table A", players: closed ? [{ id: "1", name: "Mary" }] : [{ id: "1", name: "Mary" }, { id: "2", name: "Dan" }],
    ...(closed ? { waitlist: [{ id: "2", name: "Dan" }] } : {}),
  }] }));
  await page.route("**/api/events/event/close", async (route) => {
    expect(route.request().method()).toBe("POST");
    expect(route.request().headers()["x-csrf-token"]).toBe("csrf");
    closures++;
    closed = true;
    await route.fulfill({ json: { ...event, status: "assigned", closes_at: 3799820000 } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: /Game Night open 1 table/ }).click();
  const details = page.getByRole("dialog", { name: "Game Night", exact: true });
  await expect(details.getByText("2/1", { exact: true })).toBeVisible();
  const bounds = await details.boundingBox();
  const viewport = page.viewportSize();
  expect(bounds).not.toBeNull();
  expect(viewport).not.toBeNull();
  expect(Math.abs(bounds!.x + bounds!.width / 2 - viewport!.width / 2)).toBeLessThan(2);
  expect(Math.abs(bounds!.y + bounds!.height / 2 - viewport!.height / 2)).toBeLessThan(2);
  await details.getByRole("button", { name: "Close Signups" }).click();
  const confirmation = page.getByRole("dialog", { name: "Close signups for Game Night?" });
  await expect(confirmation).toBeVisible();
  expect(closures).toBe(0);
  await confirmation.getByRole("button", { name: "Cancel", exact: true }).click();
  expect(closures).toBe(0);
  await details.getByRole("button", { name: "Close Signups" }).click();
  await confirmation.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(confirmation).toHaveCount(0);
  await expect(details.getByText("assigned", { exact: true })).toBeVisible();
  await expect(details.getByText("1/1", { exact: true })).toBeVisible();
  await expect(details.getByRole("heading", { name: "Waitlist", exact: true })).toBeVisible();
  await expect(details.locator(".table-players").getByRole("button", { name: "Mary", exact: true })).toBeVisible();
  await expect(details.locator(".table-waitlist").getByRole("button", { name: "Dan", exact: true })).toBeVisible();
  await expect(details.getByRole("button", { name: "Close Signups" })).toHaveCount(0);
  expect(closures).toBe(1);
});
