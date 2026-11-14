import { test, expect } from "./fixtures";

test("reveals closing warning inputs below event time with a one-hour default", async ({ page }) => {
  await page.route("**/api/me", route => route.fulfill({ json: { username: "organizer", csrf: "csrf" } }));
  await page.route("**/api/events", route => route.fulfill({ json: [] }));
  await page.goto("/");
  await page.locator("#event-create-button").click();
  const checkbox = page.getByRole("checkbox", { name: "Warning Message" });
  await expect(checkbox).not.toBeChecked();
  await expect(page.getByRole("textbox", { name: "Warning message" })).toHaveCount(0);
  await checkbox.check();
  await expect(page.getByRole("spinbutton", { name: "Hours before close" })).toHaveValue("1");
  await expect(page.getByRole("textbox", { name: "Warning message" })).toHaveAttribute("placeholder", "Signups close soon! Don't forget to sign up.");
  const time = await page.locator(".event-title-start-row").boundingBox();
  const warning = await checkbox.boundingBox();
  expect(warning!.y).toBeGreaterThanOrEqual(time!.y + time!.height);
});

test("cancels a scheduled occurrence only after confirmation", async ({ page }) => {
  let canceled = false;
  await page.route("**/api/me", route => route.fulfill({ json: { username: "organizer", csrf: "csrf" } }));
  await page.route("**/api/events", route => route.fulfill({ json: canceled ? [] : [{
    id: "scheduled", title: "Weekly Game Store games", status: "scheduled", series_id: "series",
    starts_at: 3800000000, scheduled_publish_at: 3799900000, duration_hours: 24,
    closes_at: 3799980000, discord_url: null, tables: [{ name: "Table A", capacity: 8 }],
  }] }));
  await page.route("**/api/recurring-series", route => route.fulfill({ json: [{ id: "series", title: "Weekly Game Store games", frequency: "weekly", time_zone: "UTC" }] }));
  await page.route("**/api/events/scheduled/cancel-scheduled", route => {
    expect(route.request().headers()["x-csrf-token"]).toBe("csrf");
    canceled = true;
    return route.fulfill({ status: 204 });
  });
  await page.goto("/");
  await page.getByText("Weekly Game Store games - weekly", { exact: true }).click();
  const trigger = page.locator("#scheduled-event-cancel-scheduled");
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: "Cancel scheduled event?" });
  await expect(dialog).toContainText("Only this occurrence will be removed");
  expect(canceled).toBe(false);
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  expect(canceled).toBe(false);
  await trigger.click();
  await dialog.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(trigger).toHaveCount(0);
  expect(canceled).toBe(true);
});
