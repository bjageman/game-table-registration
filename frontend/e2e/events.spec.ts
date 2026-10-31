import { test, expect } from "@playwright/test";

test("shows the plain placeholder page", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Register" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Login" })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
