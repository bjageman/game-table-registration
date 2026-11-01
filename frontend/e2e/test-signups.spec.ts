import { test, expect } from "@playwright/test";

for (const allowed of [true, false]) {
  test(`test signup population is ${allowed ? "available" : "hidden"} for this account`, async ({ page }) => {
    let populated = false;
    const event = { id: "event", title: "Game Night", status: "draft", starts_at: 3800000000,
      duration_hours: 24, closes_at: 3799900000, discord_url: null,
      tables: [{ name: "Table A", capacity: 8 }] };
    await page.route("**/api/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/me") return route.fulfill({ json: { username: "organizer", csrf: "csrf", can_populate_test_users: allowed } });
      if (path === "/api/events") return route.fulfill({ json: [event] });
      if (path === "/api/events/event/test-users") {
        expect(allowed).toBe(true);
        expect(route.request().postDataJSON()).toEqual({ players: 10 });
        expect(route.request().headers()["x-csrf-token"]).toBe("csrf");
        populated = true;
        return route.fulfill({ json: { ...event, is_test: true, test_generation: "new", test_user_count: 10 } });
      }
      if (path === "/api/events/event/signups") return route.fulfill({ json: [{ name: "Table A", players: populated ? Array.from({ length: 10 }, (_, i) => ({ id: `test-${i}`, name: `Test Player ${i + 1}` })) : [] }] });
      return route.fulfill({ status: 404, json: { detail: "Unexpected request" } });
    });
    await page.goto("/");
    await page.getByRole("button", { name: /^Game Night/ }).click();
    const dialog = page.getByRole("dialog", { name: "Game Night", exact: true });
    const button = dialog.getByRole("button", { name: "Populate Test Users" });
    if (!allowed) { await expect(button).toHaveCount(0); return; }
    await button.click();
    const confirmation = page.getByRole("dialog", { name: "Populate test users?", exact: true });
    await confirmation.getByLabel("Test Users").fill("10");
    await confirmation.getByRole("button", { name: "Confirm", exact: true }).click();
    await expect(dialog.getByRole("button", { name: "Test Player 1", exact: true })).toBeVisible();
    await expect(dialog.getByText("10/8", { exact: true })).toBeVisible();
    expect(populated).toBe(true);
  });
}
