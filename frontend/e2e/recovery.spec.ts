import { test, expect } from "@playwright/test";

test("reviews an existing poll and explicitly accepts uncertain late votes", async ({
  page,
}) => {
  const held = {
    id: "event",
    title: "Friday games",
    starts_at: 3800000000,
    duration_hours: 24,
    tables: [{ name: "Clocktower", capacity: 15 }],
    status: "needs_review",
    closes_at: 3799900000,
    discord_url: "https://discord.com/channels/100/200/123",
    message_id: "123",
    last_error: "Custom closing deadline was missed",
  };
  let attempts = 0;
  await page.route("**/api/me", (r) =>
    r.fulfill({ json: { username: "organizer", csrf: "csrf" } }),
  );
  await page.route("**/api/events", (r) => r.fulfill({ json: [held] }));
  await page.route("**/api/events/event/recover", (route) => {
    attempts++;
    expect(route.request().headers()["x-csrf-token"]).toBe("csrf");
    const body = route.request().postDataJSON();
    expect(body.message_id).toBe("123");
    expect(body.reason).toBe("Confirmed the existing poll in Discord");
    if (!body.accept_late_votes)
      return route.fulfill({
        status: 409,
        json: {
          detail:
            "Deadline missed; accept later votes explicitly or keep it held",
        },
      });
    return route.fulfill({
      json: {
        ...held,
        status: "closed",
        last_error: null,
        recovery_audit: [
          {
            actor: "owner",
            at: 1,
            reason: body.reason,
            accepted_late_votes: true,
          },
        ],
      },
    });
  });
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Publish to Discord" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Review existing poll" }).click();
  await expect(
    page.getByRole("button", { name: "Confirm recovery" }),
  ).toBeDisabled();
  await page
    .getByLabel("Recovery reason")
    .fill("Confirmed the existing poll in Discord");
  await page.getByRole("button", { name: "Confirm recovery" }).click();
  await expect(page.getByRole("alert")).toContainText("Deadline missed");
  await page
    .getByLabel("Accept later votes if the custom deadline was missed")
    .check();
  await page.getByRole("button", { name: "Confirm recovery" }).click();
  await expect(page.getByText("closed", { exact: true })).toBeVisible();
  await expect(
    page.getByText("A moderator accepted later votes after a missed deadline."),
  ).toBeVisible();
  expect(attempts).toBe(2);
});
