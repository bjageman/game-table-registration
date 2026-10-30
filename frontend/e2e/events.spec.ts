import { test, expect } from "@playwright/test";
test("moderator creates a draft and explicitly publishes it", async ({
  page,
}) => {
  let events: unknown[] = [];
  let publishes = 0;
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown = {};
    if (path === "/api/setup") data = { configured: true };
    else if (path === "/api/me") data = { username: "Moderator", csrf: "csrf" };
    else if (path.endsWith("/publish")) {
      publishes++;
      events = [
        {
          ...(events[0] as object),
          status: "open",
          discord_url: "https://discord.com/channels/1/2/3",
        },
      ];
      data = events[0];
    } else if (path === "/api/events" && route.request().method() === "POST") {
      const body = route.request().postDataJSON();
      expect(body.tables).toEqual([{ name: "Clocktower", capacity: 15 }]);
      events = [
        {
          ...body,
          id: "event",
          status: "draft",
          starts_at: Date.parse(body.starts_at) / 1000,
          closes_at: null,
          discord_url: null,
        },
      ];
      data = events[0];
    } else if (path === "/api/events") data = events;
    await route.fulfill({ json: data });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "New game night" }).click();
  await page.getByLabel("Event name").fill("Friday games");
  await page.getByLabel("Event date & time").fill("2030-01-25T19:00");
  await page.getByLabel("Table name").fill("Clocktower");
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByText("Draft saved.", { exact: false })).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Publish to Discord" }).click();
  await expect(page.getByRole("link", { name: "View poll" })).toBeVisible();
  expect(publishes).toBe(1);
  await expect(
    page.getByRole("button", { name: "Publish to Discord" }),
  ).toHaveCount(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
