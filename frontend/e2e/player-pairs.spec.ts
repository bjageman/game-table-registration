import { test, expect } from "./fixtures";

test("pairs players reciprocally after confirming replacement of an existing pair", async ({ page }) => {
  const names: Record<string, string> = { "1": "Alice", "2": "Bob", "3": "Carol", "4": "Dave" };
  const partners: Record<string, string | null> = { "1": "2", "2": "1", "3": "4", "4": "3" };
  const profile = (id: string) => ({ discord_id: id, discord_name: names[id], real_name: "", weighting: 5,
    guaranteed_seat: false, is_test: false, partner: partners[id] ? { id: partners[id], name: names[partners[id]!] } : null });
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/me") return route.fulfill({ json: { username: "organizer", csrf: "csrf" } });
    if (path === "/api/players") return route.fulfill({ json: Object.keys(names).map(profile) });
    const match = path.match(/^\/api\/players\/(\d+)(\/partner)?$/);
    if (!match) return route.fallback();
    const id = match[1];
    if (!match[2]) return route.fulfill({ json: profile(id) });
    const body = route.request().postDataJSON();
    expect(route.request().headers()["x-csrf-token"]).toBe("csrf");
    if (!body.replace_partner_id) return route.fulfill({ json: {
      confirmation_required: true, replace_partner_id: "4", message: "This will break the link between Carol and Dave. Continue?",
    } });
    partners["2"] = null; partners["4"] = null;
    partners["1"] = "3"; partners["3"] = "1";
    return route.fulfill({ json: { profile: profile(id) } });
  });
  await page.goto("/#/players");
  await page.locator("#player-open-1").click();
  await expect(page.getByText("Linked to Bob", { exact: false })).toBeVisible();
  await page.getByRole("searchbox", { name: "Search for a player to link" }).fill("Carol");
  await page.getByRole("button", { name: "Link Carol (3)" }).click();
  const confirmation = page.getByRole("dialog", { name: "Replace player link?" });
  await expect(confirmation).toContainText("Carol and Dave");
  expect(partners["1"]).toBe("2");
  await confirmation.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(page.getByText("Linked to Carol", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Close player information" }).click();
  await page.locator("#player-open-3").click();
  await expect(page.getByText("Linked to Alice", { exact: false })).toBeVisible();
});
