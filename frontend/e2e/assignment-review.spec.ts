import { test, expect } from "./fixtures";

test("reviews a saved draw before confirming its publication to Discord", async ({ page }) => {
  let status = "open";
  let approvals = 0;
  const event = () => ({ id: "event", title: "Review Night", status, starts_at: 3800000000,
    duration_hours: 24, closes_at: 3799900000, discord_url: "https://discord.com/poll",
    tables: [{ name: "Table A", capacity: 1 }] });
  await page.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/events/event/close") {
      status = "review";
      return route.fulfill({ json: event() });
    }
    if (path === "/api/events/event/assignments/approve") {
      expect(route.request().headers()["x-csrf-token"]).toBe("csrf");
      approvals++;
      status = "assigned";
      return route.fulfill({ json: event() });
    }
    const json = path === "/api/me" ? { username: "organizer", csrf: "csrf" }
      : path === "/api/events" ? [event()]
      : path.endsWith("/signups") ? [{ name: "Table A", players: [{ id: "1", name: "Alice" }],
        waitlist: status === "open" ? [] : [{ id: "2", name: "Bob" }] }]
      : path.endsWith("/announcement") ? { status: "sent", error: null, url: "https://discord.com/announcement" }
      : undefined;
    return json === undefined ? route.fallback() : route.fulfill({ json });
  });
  await page.goto("/");
  await page.locator("#event-open-event").click();
  await page.getByRole("button", { name: "Close Signups", exact: true }).click();
  await page.getByRole("dialog", { name: "Close signups for Review Night?" }).getByRole("button", { name: "Confirm", exact: true }).click();
  const review = page.locator("#event-dialog-event");
  await expect(review).toBeVisible();
  await expect(page.getByText("Alice", { exact: true })).toBeVisible();
  await expect(page.getByRole("list", { name: "Waitlist for Table A" })).toHaveText("Bob");
  await expect(page.getByRole("button", { name: "Add Player", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Add Bob to Table A" })).toBeVisible();
  expect(approvals).toBe(0);
  // Closing the page does not discard or publish the saved preview.
  await page.reload();
  await page.locator("#event-open-event").click();
  await expect(review).toBeVisible();
  expect(approvals).toBe(0);
  await page.getByRole("button", { name: "Send to Discord" }).click();
  await expect(review).not.toBeVisible();
  await expect(page.getByRole("button", { name: "Add Player", exact: true })).toBeVisible();
  expect(approvals).toBe(1);
});
