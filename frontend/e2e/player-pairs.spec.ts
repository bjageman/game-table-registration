import { test, expect } from "./fixtures";

test("manages reciprocal preferences without linking preferences to each other", async ({ page }) => {
  const names: Record<string, string> = { "1": "Alice", "2": "Bob", "3": "Carol", "4": "Dave" };
  const preferences: Record<string, string[]> = { "1": ["2"], "2": ["1"], "3": ["4"], "4": ["3"] };
  const profile = (id: string) => ({ discord_id: id, discord_name: names[id], real_name: "", weighting: 5,
    guaranteed_seat: false, is_test: false, paired_preferences: preferences[id].map((pid) => ({ id: pid, name: names[pid] })) });
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/me") return route.fulfill({ json: { username: "organizer", csrf: "csrf" } });
    if (path === "/api/players") return route.fulfill({ json: Object.keys(names).map(profile) });
    const match = path.match(/^\/api\/players\/(\d+)(\/pairings)?$/);
    if (!match) return route.fallback();
    const id = match[1];
    if (!match[2]) return route.fulfill({ json: profile(id) });
    const targets: string[] = route.request().postDataJSON().player_ids;
    expect(route.request().headers()["x-csrf-token"]).toBe("csrf");
    for (const pid of Object.keys(names)) {
      if (pid === id) continue;
      preferences[pid] = preferences[pid].filter((other) => other !== id);
      if (targets.includes(pid)) preferences[pid].push(id);
    }
    preferences[id] = targets;
    return route.fulfill({ json: { profile: profile(id) } });
  });
  await page.goto("/#/players");
  await expect(page.getByRole("button", { name: "Sort by Paired Player Preferences" })).toBeVisible();
  await page.locator("#player-open-1").click();
  const dialog = page.getByRole("dialog", { name: "Player Information" });
  await expect(dialog.getByText("Bob", { exact: true })).toBeVisible();
  await dialog.getByRole("combobox", { name: "Paired Player Preferences" }).fill("Carol");
  await page.getByRole("option", { name: "Carol (3)" }).click();
  await expect(dialog.getByText("Carol", { exact: true })).toBeVisible();
  expect(preferences["1"]).toEqual(["2", "3"]);
  expect(preferences["2"]).toEqual(["1"]);
  expect(preferences["3"]).toEqual(["4", "1"]);
  await dialog.getByRole("button", { name: "Close player information" }).click();
  await expect(page.locator("#player-open-1 .player-lookup-partner")).toHaveText("Bob, Carol");
  await page.locator("#player-open-3").click();
  await expect(dialog.getByText("Alice", { exact: true })).toBeVisible();
  await expect(dialog.getByText("Dave", { exact: true })).toBeVisible();
  await dialog.getByRole("combobox").press("Backspace");
  await expect(dialog.getByText("Alice", { exact: true })).toHaveCount(0);
  expect(preferences["1"]).toEqual(["2"]);
  expect(preferences["3"]).toEqual(["4"]);
});
