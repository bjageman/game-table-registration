import { test, expect } from "./fixtures";

test("searches event titles and sorts by title or event date", async ({ page }) => {
  const draft = { status: "draft", duration_hours: 24, closes_at: null, discord_url: null, tables: [{ name: "Clocktower", capacity: 8 }] };
  await page.route("**/api/me", (route) => route.fulfill({ json: { username: "organizer", csrf: "csrf" } }));
  await page.route("**/api/events", (route) => route.fulfill({ json: [
    { ...draft, id: "a", title: "Alpha Night", starts_at: 2000000300, created_at: 100 },
    { ...draft, id: "b", title: "Beta Night", starts_at: 2000000100, created_at: 300 },
    { ...draft, id: "z", title: "Zebra Night", starts_at: 2000000200, created_at: 200 },
    { ...draft, id: "archived", title: "Alpha Archived", starts_at: 2000000400, created_at: 50, archived_at: 2000000000 },
  ] }));
  await page.goto("/");
  const titles = page.locator(".event-list-title");
  const search = page.getByRole("searchbox", { name: "Search events" });
  await expect(search).toBeVisible();
  await expect(page.getByRole("heading", { name: "Game Events", exact: true })).toHaveCount(0);
  await expect(titles).toHaveText(["Beta Night", "Zebra Night", "Alpha Night"]);
  for (const [label, expected] of [
    ["Event Date", ["Alpha Night", "Zebra Night", "Beta Night"]],
    ["Event Date", ["Beta Night", "Zebra Night", "Alpha Night"]],
    ["Event Name", ["Zebra Night", "Beta Night", "Alpha Night"]],
    ["Event Name", ["Alpha Night", "Beta Night", "Zebra Night"]],
    ["Creation Date", ["Beta Night", "Zebra Night", "Alpha Night"]],
    ["Creation Date", ["Alpha Night", "Zebra Night", "Beta Night"]],
  ] as const) {
    await page.getByRole("button", { name: "Sort events", exact: true }).click();
    await page.getByRole("menuitemradio", { name: label }).click();
    await expect(titles).toHaveText([...expected]);
  }
  await search.fill(" alpha ");
  await expect(titles).toHaveText(["Alpha Night"]);
  await page.getByRole("checkbox", { name: "Archived", exact: true }).check();
  await expect(titles).toHaveText(["Alpha Archived", "Alpha Night"]);
  await search.fill("Clocktower");
  await expect(page.getByRole("heading", { name: "No Matching Events" })).toBeVisible();
  await search.fill("");
  await expect(titles).toHaveCount(4);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
