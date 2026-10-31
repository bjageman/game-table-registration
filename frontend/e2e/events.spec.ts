import { test, expect } from "@playwright/test";

test("offers Discord login without exposing moderator content", async ({
  page,
}) => {
  await page.route("**/api/me", (route) =>
    route.fulfill({ status: 401, json: { detail: "Sign in" } }),
  );
  await page.route("**/api/setup", (route) =>
    route.fulfill({ json: { configured: true } }),
  );
  await page.goto("/");
  await expect(
    page.getByRole("link", { name: "Log in with Discord" }),
  ).toHaveAttribute("href", "/api/auth/login");
  await expect(page.getByRole("button", { name: "Log out" })).toHaveCount(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("restores a session and logs out", async ({ page }) => {
  await page.route("**/api/events", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/me", (route) =>
    route.fulfill({ json: { username: "organizer", csrf: "test-csrf" } }),
  );
  await page.route("**/api/auth/logout", async (route) => {
    expect(route.request().method()).toBe("POST");
    expect(route.request().headers()["x-csrf-token"]).toBe("test-csrf");
    await route.fulfill({ status: 204 });
  });
  await page.goto("/");
  await expect(page.getByText("organizer", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "organizer" }).click();
  await page.getByRole("menuitem", { name: "Log Out" }).click();
  await expect(
    page.getByRole("link", { name: "Log in with Discord" }),
  ).toBeVisible();
});
