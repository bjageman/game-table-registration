import { test, expect } from "@playwright/test";

const session = { username: "organizer", csrf: "test-csrf" };
const occurrence = {
  date: "2090-06-16",
  skipped: false,
  opens_at: 3800000000,
  signup_closes_at: 3800086400,
  starts_at: 3800172800,
};

test("previews weekly dates before activation, edits future dates and pauses safely", async ({
  page,
}) => {
  let schedules: Record<string, unknown>[] = [];
  let creations = 0;
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/me") return route.fulfill({ json: session });
    if (path === "/api/events") return route.fulfill({ json: [] });
    if (path === "/api/schedules" && route.request().method() === "GET")
      return route.fulfill({ json: schedules });
    expect(route.request().headers()["x-csrf-token"]).toBe(session.csrf);
    const body = route.request().postDataJSON();
    if (path.endsWith("/preview"))
      return route.fulfill({
        json: [
          {
            ...occurrence,
            skipped: body.skip_dates.includes(occurrence.date),
            action: schedules.length ? "update" : undefined,
          },
        ],
      });
    if (path === "/api/schedules") {
      creations++;
      expect(route.request().headers()["idempotency-key"]).toBeTruthy();
      schedules = [
        { ...body, id: "weekly", active: true, revision: 1, last_error: null },
      ];
      return route.fulfill({ status: 201, json: schedules[0] });
    }
    if (
      path === "/api/schedules/weekly" &&
      route.request().method() === "PUT"
    ) {
      expect(body.revision).toBe(1);
      schedules = [{ ...schedules[0], ...body, revision: 2 }];
      return route.fulfill({ json: schedules[0] });
    }
    if (path === "/api/schedules/weekly/active") {
      expect(body.revision).toBe(schedules[0].revision);
      schedules = [
        {
          ...schedules[0],
          active: body.active,
          revision: Number(schedules[0].revision) + 1,
        },
      ];
      return route.fulfill({ json: schedules[0] });
    }
    return route.fulfill({
      status: 404,
      json: { detail: "Unexpected request" },
    });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Manage weekly schedules" }).click();
  await page.getByRole("button", { name: "Create weekly schedule" }).click();
  await page
    .getByLabel("Schedule title", { exact: true })
    .fill("Friday nights");
  await page.getByLabel("Weekly table 1 name").fill("Clocktower");
  await expect(
    page.getByRole("button", { name: "Confirm weekly schedule" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Preview dates" }).click();
  await expect(page.getByText(/Next eight weeks/)).toBeVisible();
  expect(creations).toBe(0);
  await page.getByRole("button", { name: "Confirm weekly schedule" }).click();
  await expect(
    page.getByRole("heading", { name: "Friday nights" }),
  ).toBeVisible();
  expect(creations).toBe(1);
  await page.getByRole("button", { name: "Edit future occurrences" }).click();
  await page
    .getByLabel("Schedule title", { exact: true })
    .fill("Saturday nights");
  await page.getByRole("button", { name: "Preview dates" }).click();
  await page.getByLabel("Skip this week").check();
  await page.getByRole("button", { name: "Confirm future changes" }).click();
  await expect(
    page.getByRole("heading", { name: "Saturday nights" }),
  ).toBeVisible();
  expect(schedules[0].skip_dates).toEqual([occurrence.date]);
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Pause schedule" }).click();
  await expect(
    page.getByRole("button", { name: "Resume schedule" }),
  ).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Resume schedule" }).click();
  await expect(
    page.getByRole("button", { name: "Pause schedule" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("blocks invalid DST preview dates until explicitly skipped", async ({
  page,
}) => {
  await page.route("**/api/me", (r) => r.fulfill({ json: session }));
  await page.route("**/api/events", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/schedules", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/schedules/preview", (r) =>
    r.fulfill({
      json: [
        {
          date: "2090-03-12",
          skipped: false,
          error: "Local time is missing or ambiguous",
        },
      ],
    }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Manage weekly schedules" }).click();
  await page.getByRole("button", { name: "Create weekly schedule" }).click();
  await page.getByRole("button", { name: "Preview dates" }).click();
  await expect(
    page.getByRole("button", { name: "Confirm weekly schedule" }),
  ).toBeDisabled();
  await page.getByLabel("Skip this week").check();
  await expect(
    page.getByRole("button", { name: "Confirm weekly schedule" }),
  ).toBeEnabled();
  await page.getByLabel("Schedule title", { exact: true }).fill("Changed");
  await expect(
    page.getByRole("button", { name: "Confirm weekly schedule" }),
  ).toHaveCount(0);
});
