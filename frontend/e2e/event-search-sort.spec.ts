import { test, expect } from "@playwright/test";

test("searches event titles and sorts by title or event date", async ({ page }) => {
  const draft = { status: "draft", duration_hours: 24, closes_at: null, discord_url: null, tables: [{ name: "Clocktower", capacity: 8 }] };
  await page.route("**/api/me", (route) => route.fulfill({ json: { username: "organizer", csrf: "csrf" } }));
  await page.route("**/api/events", (route) => route.fulfill({ json: [
    { ...draft, id: "a", title: "Alpha Night", starts_at: 2000000300 },
    { ...draft, id: "b", title: "Beta Night", starts_at: 2000000100 },
    { ...draft, id: "z", title: "Zebra Night", starts_at: 2000000200 },
    { ...draft, id: "archived", title: "Alpha Archived", starts_at: 2000000400, archived_at: 2000000000 },
  ] }));
  await page.goto("/");
  const titles = page.locator(".event-list-title");
  const search = page.getByRole("searchbox", { name: "Search events" });
  await expect(search).toBeVisible();
  await expect(page.getByRole("heading", { name: "Game Events", exact: true })).toHaveCount(0);
  await expect(titles).toHaveText(["Beta Night", "Zebra Night", "Alpha Night"]);
  for (const [label, expected] of [
    ["Event Date: Latest First", ["Alpha Night", "Zebra Night", "Beta Night"]],
    ["Title: A–Z", ["Alpha Night", "Beta Night", "Zebra Night"]],
    ["Title: Z–A", ["Zebra Night", "Beta Night", "Alpha Night"]],
  ] as const) {
    await page.getByRole("button", { name: "Sort events", exact: true }).click();
    await page.getByRole("menuitemradio", { name: label }).click();
    await expect(titles).toHaveText([...expected]);
  }
  await search.fill(" alpha ");
  await expect(titles).toHaveText(["Alpha Night"]);
  await page.getByLabel("Show Archived").check();
  await expect(titles).toHaveText(["Alpha Night", "Alpha Archived"]);
  await search.fill("Clocktower");
  await expect(page.getByRole("heading", { name: "No Matching Events" })).toBeVisible();
  await search.fill("");
  await expect(titles).toHaveCount(4);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
