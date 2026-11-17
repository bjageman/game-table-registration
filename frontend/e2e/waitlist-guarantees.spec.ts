import { test, expect } from "./fixtures";

test("waitlist guarantees default off with five hours and retain a saved cutoff", async ({ page }) => {
  let enabled = false;
  let hours = 5;
  let keep = true;
  await page.route("**/api/me", route => route.fulfill({ json: { username: "organizer", csrf: "csrf" } }));
  await page.route("**/api/settings", route => route.fulfill({ json: { selection: null, connect_url: "/api/auth/connect" } }));
  await page.route("**/api/settings/assignment", route => {
    if (route.request().method() === "PUT") {
      expect(route.request().headers()["x-csrf-token"]).toBe("csrf");
      enabled = route.request().postDataJSON().guarantee_waitlisted_players;
      hours = route.request().postDataJSON().waitlist_guarantee_retention_hours;
      keep = route.request().postDataJSON().keep_waitlist_guarantee_on_short_notice;
    }
    return route.fulfill({ json: { automatic_weight_adjustment: true, announce_table_changes: true,
      guarantee_waitlisted_players: enabled, waitlist_guarantee_retention_hours: hours, keep_waitlist_guarantee_on_short_notice: keep } });
  });
  await page.goto("/#/settings");
  await page.getByRole("tab", { name: "General", exact: true }).click();
  const option = page.getByRole("checkbox", { name: "Waitlisted players will be guaranteed a seat for the next event" });
  await expect(option).not.toBeChecked();
  await option.click();
  const cutoff = page.getByRole("spinbutton", { name: "Hours before event" });
  await expect(cutoff).toBeEnabled();
  await expect(cutoff).toHaveValue("5");
  await cutoff.fill("3");
  await cutoff.blur();
  await expect.poll(() => hours).toBe(3);
  await page.reload();
  await page.getByRole("tab", { name: "General", exact: true }).click();
  await expect(option).toBeChecked();
  await expect(cutoff).toHaveValue("3");
  const shortNotice = page.getByRole("checkbox", { name: "Player keeps the guarantee if placed on short notice" });
  await expect(shortNotice).toBeChecked();
  const parentBounds = await option.boundingBox();
  const childBounds = await shortNotice.boundingBox();
  const labelBounds = await shortNotice.locator("xpath=ancestor::label").boundingBox();
  const inputBounds = await page.locator(".short-notice-hours").boundingBox();
  expect(childBounds!.x).toBeGreaterThan(parentBounds!.x + 20);
  expect(inputBounds!.x).toBeGreaterThanOrEqual(labelBounds!.x + labelBounds!.width);
  expect(inputBounds!.width).toBeLessThanOrEqual(130);
  await shortNotice.click();
  await expect.poll(() => keep).toBe(false);
  await expect(cutoff).toBeDisabled();
  await expect(cutoff).toHaveValue("3");
  await expect(page.getByText("0 disables the late-promotion exception.")).toHaveCount(0);
  await page.reload();
  await page.getByRole("tab", { name: "General", exact: true }).click();
  await expect(shortNotice).not.toBeChecked();
  await expect(cutoff).toBeDisabled();
  await expect(cutoff).toHaveValue("3");
  await option.click();
  await expect.poll(() => enabled).toBe(false);
  await expect(cutoff).toHaveCount(0);
});
