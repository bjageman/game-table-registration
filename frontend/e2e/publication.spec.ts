import { test, expect } from "@playwright/test";

const draft = {
  id: "event-1",
  title: "Friday games",
  starts_at: 3800000000,
  duration_hours: 24,
  tables: [{ name: "Clocktower", capacity: 15 }],
  status: "draft",
  closes_at: null,
  discord_url: null,
};

test.beforeEach(async ({ page }) => {
  await page.route("**/api/me", (route) =>
    route.fulfill({ json: { username: "organizer", csrf: "csrf" } }),
  );
  await page.route("**/api/events", (route) =>
    route.fulfill({ json: [draft] }),
  );
});

test("requires confirmation and replaces the publish action with a Discord link", async ({
  page,
}) => {
  let publications = 0;
  await page.route("**/api/events/event-1/publish", async (route) => {
    publications++;
    expect(route.request().headers()["x-csrf-token"]).toBe("csrf");
    expect(route.request().method()).toBe("POST");
    await route.fulfill({
      json: {
        ...draft,
        status: "open",
        closes_at: 2000000000,
        discord_url: "https://discord.com/channels/guild/channel/message",
      },
    });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Publish to Discord" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Cancel", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(publications).toBe(0);
  await page.getByRole("button", { name: "Publish to Discord" }).click();
  await page.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(
    page.getByRole("link", { name: /View Discord poll/ }),
  ).toHaveAttribute(
    "href",
    "https://discord.com/channels/guild/channel/message",
  );
  await expect(
    page.getByRole("button", { name: "Publish to Discord" }),
  ).toHaveCount(0);
  expect(publications).toBe(1);
});

test("holds uncertain publication instead of offering a duplicate request", async ({
  page,
}) => {
  let publications = 0;
  await page.route("**/api/events/event-1/publish", async (route) => {
    publications++;
    await route.fulfill({
      status: 502,
      json: { detail: "Check Discord before retrying" },
    });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Publish to Discord" }).click();
  await page.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(page.getByText("unconfirmed", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Publish to Discord" }),
  ).toHaveCount(0);
  expect(publications).toBe(1);
});
