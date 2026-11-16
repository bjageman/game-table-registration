import { test, expect } from "./fixtures";

test("swaps a seat with a waitlist placement and saves the promotion setting", async ({ page }) => {
  let swapped = false;
  let autoPromote = true;
  const tables = [{ name: "A", capacity: 1 }, { name: "B", capacity: 1 }];
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/me") return route.fulfill({ json: { username: "organizer", csrf: "csrf" } });
    if (path.endsWith("/announcement")) return route.fulfill({ json: { status: "sent", error: null, url: null } });
    if (path.endsWith("/swap-players")) {
      expect(route.request().headers()["x-csrf-token"]).toBe("csrf");
      expect(route.request().postDataJSON()).toEqual({ player_id: "1", table: "A", waitlist: false, other_player_id: "4", other_table: "B", other_waitlist: true });
      swapped = true;
      return route.fulfill({ json: { ok: true } });
    }
    if (path.endsWith("/waitlist-settings")) {
      autoPromote = route.request().postDataJSON().auto_promote_waitlist;
      return route.fulfill({ json: { auto_promote_waitlist: autoPromote } });
    }
    if (path === "/api/events") return route.fulfill({ json: [{
      id: "event", title: "Assigned Event", status: "assigned", starts_at: 3800000000,
      duration_hours: 24, closes_at: 3799900000, discord_url: null, tables,
      auto_promote_waitlist: autoPromote,
    }] });
    if (path.endsWith("/signups")) return route.fulfill({ json: [
      { name: "A", players: [{ id: swapped ? "4" : "1", name: swapped ? "Daniel" : "Alice" }], waitlist: [{ id: "2", name: "Bob" }] },
      { name: "B", players: [{ id: "3", name: "Carol" }], waitlist: [{ id: swapped ? "1" : "4", name: swapped ? "Alice" : "Daniel" }] },
    ] });
    return route.fallback();
  });
  await page.goto("/");
  await page.locator("#event-open-event").click();
  const checkbox = page.getByRole("checkbox", { name: "Auto-promote waitlisted players" });
  await expect(checkbox).toBeChecked();
  await checkbox.click();
  await expect(checkbox).not.toBeChecked();
  // The owner sees the saved choice even after reopening the event modal.
  await page.getByRole("button", { name: "Close event", exact: true }).click();
  await page.locator("#event-open-event").click();
  await expect(checkbox).not.toBeChecked();
  const setting = page.locator(".waitlist-promotion-setting");
  await expect(setting).toHaveCSS("margin-bottom", "20px");
  const swap = page.getByRole("button", { name: "Swap Alice at A", exact: true });
  const remove = page.getByRole("button", { name: "Remove Alice from table", exact: true });
  const swapBounds = await swap.boundingBox();
  const removeBounds = await remove.boundingBox();
  expect(swapBounds!.x + swapBounds!.width).toBeLessThanOrEqual(removeBounds!.x);
  await swap.click();
  const dialog = page.getByRole("dialog", { name: "Swap Alice", exact: true });
  await expect(dialog.getByRole("button", { name: /Bob/ })).toBeVisible();
  await dialog.getByRole("searchbox", { name: "Search players to swap" }).fill("dan");
  await dialog.getByRole("button", { name: /Daniel.*Waitlist/ }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole("button", { name: "Swap Daniel at A", exact: true })).toBeVisible();
  await expect(page.getByRole("list", { name: "Waitlist for B" })).toContainText("Alice");
});

test("open signups hide swaps and align the Wt heading with scores", async ({ page }) => {
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/me") return route.fulfill({ json: { username: "organizer", csrf: "csrf" } });
    if (path === "/api/events") return route.fulfill({ json: [{
      id: "event", title: "Open Event", status: "open", starts_at: 3800000000,
      duration_hours: 24, closes_at: 3799900000, discord_url: null,
      tables: [{ name: "A", capacity: 1 }, { name: "B", capacity: 1 }],
    }] });
    if (path.endsWith("/signups")) return route.fulfill({ json: [
      { name: "A", players: [{ id: "1", name: "Alice", weighting: 7 }] },
      { name: "B", players: [{ id: "2", name: "Bob", weighting: 5 }] },
    ] });
    return route.fallback();
  });
  await page.goto("/");
  await page.locator("#event-open-event").click();
  await expect(page.getByRole("checkbox", { name: "Auto-promote waitlisted players" })).toHaveCount(0);
  const table = page.locator("#event-event-table-1");
  const header = table.getByRole("button", { name: "Sort A by weight" });
  const score = table.getByRole("button", { name: "Edit weight for Alice: 7.0" });
  await expect(score).toBeVisible();
  const headingBounds = await header.boundingBox();
  const scoreBounds = await score.boundingBox();
  expect(Math.abs(headingBounds!.x + headingBounds!.width - scoreBounds!.x - scoreBounds!.width)).toBeLessThan(1);
  await expect(page.getByRole("button", { name: /^Swap / })).toHaveCount(0);
});

for (const fromWaitlist of [false, true]) {
  test(`swaps a same-table seat and waitlist entry from ${fromWaitlist ? "the waitlist" : "the seat"}`, async ({ page }) => {
    let swapped = false;
    await page.route("**/api/**", (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/me") return route.fulfill({ json: { username: "organizer", csrf: "csrf" } });
      if (path.endsWith("/announcement")) return route.fulfill({ json: { status: "sent", error: null, url: null } });
      if (path.endsWith("/swap-players")) {
        expect(route.request().postDataJSON()).toEqual({ player_id: fromWaitlist ? "2" : "1", table: "A", waitlist: fromWaitlist, other_player_id: fromWaitlist ? "1" : "2", other_table: "A", other_waitlist: !fromWaitlist });
        swapped = true;
        return route.fulfill({ json: { ok: true } });
      }
      if (path === "/api/events") return route.fulfill({ json: [{
        id: "event", title: "Assigned Event", status: "assigned", starts_at: 3800000000,
        duration_hours: 24, closes_at: 3799900000, discord_url: null,
        tables: [{ name: "A", capacity: 1 }],
      }] });
      if (path.endsWith("/signups")) return route.fulfill({ json: [{
        name: "A", players: [{ id: swapped ? "2" : "1", name: swapped ? "Bob" : "Alice" }],
        waitlist: [{ id: swapped ? "1" : "2", name: swapped ? "Alice" : "Bob" }],
      }] });
      return route.fallback();
    });
    await page.goto("/");
    await page.locator("#event-open-event").click();
    await page.getByRole("button", { name: fromWaitlist ? "Swap Bob on A waitlist" : "Swap Alice at A", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: fromWaitlist ? "Swap Bob" : "Swap Alice", exact: true });
    await dialog.getByRole("button", { name: fromWaitlist ? /Alice.*Seated/ : /Bob.*Waitlist/ }).click();
    await expect(dialog).not.toBeVisible();
    await expect(page.getByRole("button", { name: "Swap Bob at A", exact: true })).toBeVisible();
    await expect(page.getByRole("list", { name: "Waitlist for A" })).toContainText("Alice");
  });
}
