import { test, expect, type Page } from "@playwright/test";

const session = { username: "organizer", csrf: "test-csrf" };
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

async function signIn(page: Page) {
  await page.route("**/api/me", (route) => route.fulfill({ json: session }));
}
async function fillDraft(page: Page) {
  await page.getByRole("button", { name: "Create event", exact: true }).click();
  await page.getByLabel(/Event title/).fill("Friday games");
  await setDateTime(page, "June", "14", "2090", "07", "00", "PM");
  await page.getByLabel(/Table 1 name/).fill("Clocktower");
}
async function setDateTime(
  page: Page,
  month: string,
  day: string,
  year: string,
  hours: string,
  minutes: string,
  meridiem: string,
) {
  for (const [name, value] of [
    ["Month", month],
    ["Day", day],
    ["Year", year],
    ["Hours", hours],
    ["Minutes", minutes],
    ["Meridiem", meridiem],
  ]) {
    const dateField = page.getByRole("group", { name: /^Event starts/ });
    const mobileTime = page.getByRole("group", { name: /^Event time/ });
    const field =
      ["Hours", "Minutes", "Meridiem"].includes(name) &&
      (await mobileTime.count())
        ? mobileTime
        : dateField;
    await field.getByRole("spinbutton", { name, exact: true }).fill(value);
  }
}

test("completes login, timed draft creation, scheduling, refresh, and logout", async ({
  page,
}) => {
  let signedIn = false;
  let events: (typeof draft)[] = [];
  let creations = 0;
  let publications = 0;
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/me")
      return route.fulfill({
        status: signedIn ? 200 : 401,
        json: signedIn ? session : { detail: "Sign in" },
      });
    if (path === "/api/setup")
      return route.fulfill({ json: { configured: true } });
    if (path === "/api/auth/login") {
      signedIn = true;
      return route.fulfill({ status: 302, headers: { location: "/" } });
    }
    if (path === "/api/auth/logout") {
      expect(route.request().headers()["x-csrf-token"]).toBe(session.csrf);
      signedIn = false;
      return route.fulfill({ status: 204 });
    }
    if (path === "/api/events" && route.request().method() === "GET")
      return route.fulfill({ json: events });
    if (path === "/api/events" && route.request().method() === "POST") {
      creations++;
      expect(route.request().headers()["x-csrf-token"]).toBe(session.csrf);
      const body = route.request().postDataJSON();
      expect(body.starts_at).toMatch(/Z$/);
      expect(body.tables).toEqual([{ name: "Clocktower", capacity: 15 }]);
      events = [
        {
          ...draft,
          ...body,
          starts_at: Date.parse(body.starts_at) / 1000,
          opens_at: Date.parse(body.opens_at) / 1000,
          signup_closes_at: Date.parse(body.signup_closes_at) / 1000,
        },
      ];
      return route.fulfill({ status: 201, json: events[0] });
    }
    if (path === "/api/events/event-1/schedule") {
      publications++;
      expect(route.request().headers()["x-csrf-token"]).toBe(session.csrf);
      const published = {
        ...events[0],
        status: "scheduled",
        closes_at: 3800000000,
        discord_url: null,
      };
      events = [published as unknown as typeof draft];
      return route.fulfill({ json: published });
    }
    return route.fulfill({
      status: 404,
      json: { detail: "Unexpected request" },
    });
  });
  await page.goto("/");
  await page.getByRole("link", { name: "Log in with Discord" }).click();
  await expect(
    page.getByRole("heading", { name: "No events yet" }),
  ).toBeVisible();
  await fillDraft(page);
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(
    page.getByRole("heading", { name: "Friday games" }),
  ).toBeVisible();
  await expect(page.getByText("draft", { exact: true })).toBeVisible();
  await expect(page.getByRole("status")).toBeFocused();
  expect(publications).toBe(0);
  await page.getByRole("button", { name: "Publish to Discord" }).click();
  await page.getByRole("button", { name: "Confirm publication" }).click();
  await expect(page.getByText("scheduled", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Refresh events" }).click();
  await expect(page.getByText("scheduled", { exact: true })).toBeVisible();
  expect(creations).toBe(1);
  expect(publications).toBe(1);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(
    page.getByRole("link", { name: "Log in with Discord" }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "Friday games" })).toHaveCount(
    0,
  );
});

test("keeps event values and associates backend validation with its field", async ({
  page,
}) => {
  await signIn(page);
  await page.route("**/api/events", async (route) => {
    if (route.request().method() === "GET") return route.fulfill({ json: [] });
    return route.fulfill({
      status: 422,
      json: {
        detail: [
          {
            loc: ["body", "tables", 0, "capacity"],
            msg: "Capacity was rejected by the server",
          },
        ],
      },
    });
  });
  await page.goto("/");
  await fillDraft(page);
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByRole("alert")).toContainText("Capacity was rejected");
  await expect(page.getByLabel(/Table 1 capacity/)).toHaveAttribute(
    "aria-invalid",
    "true",
  );
  await expect(page.getByLabel(/Table 1 capacity/)).toHaveAccessibleDescription(
    "Capacity was rejected by the server",
  );
  await expect(page.getByLabel(/Event title/)).toHaveValue("Friday games");
});

for (const status of [401, 403]) {
  test(`hides private events after access is lost (${status})`, async ({
    page,
  }) => {
    await signIn(page);
    let expired = false;
    await page.route("**/api/events", (route) =>
      route.fulfill({
        status: expired ? status : 200,
        json: expired ? { detail: "Access removed" } : [draft],
      }),
    );
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "Friday games" }),
    ).toBeVisible();
    expired = true;
    await page.getByRole("button", { name: "Refresh events" }).click();
    if (status === 401)
      await expect(
        page.getByRole("link", { name: "Log in with Discord" }),
      ).toBeVisible();
    else
      await expect(
        page.getByRole("heading", { name: "Moderator access required" }),
      ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Friday games" }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Create event", exact: true }),
    ).toHaveCount(0);
  });
}

test("shows loading, recovers from a failed event request, and distinguishes an empty list", async ({
  page,
}) => {
  await signIn(page);
  let release: () => void = () => {};
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  let failed = true;
  await page.route("**/api/events", async (route) => {
    await pending;
    return route.fulfill({
      status: failed ? 503 : 200,
      json: failed ? { detail: "Service unavailable" } : [],
    });
  });
  await page.goto("/");
  await expect(page.getByRole("status")).toHaveText("Loading events…");
  await expect(
    page.getByRole("button", { name: "Create event", exact: true }),
  ).toBeDisabled();
  release();
  await expect(page.getByRole("alert")).toHaveText("Service unavailable");
  await expect(page.getByText("No events yet")).toHaveCount(0);
  failed = false;
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByText("No events yet")).toBeVisible();
});

for (const outcome of ["network", "conflict"] as const) {
  test(`does not repeat publication after ${outcome} failure`, async ({
    page,
  }) => {
    await signIn(page);
    await page.route("**/api/events", (route) =>
      route.fulfill({ json: [draft] }),
    );
    let calls = 0;
    await page.route("**/api/events/event-1/publish", async (route) => {
      calls++;
      if (outcome === "network") return route.abort("failed");
      return route.fulfill({
        status: 409,
        json: { detail: "Already published or awaiting publish review" },
      });
    });
    await page.goto("/");
    await page.getByRole("button", { name: "Publish to Discord" }).click();
    await page.getByRole("button", { name: "Confirm publication" }).click();
    await expect(page.getByText("unconfirmed", { exact: true })).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Publish to Discord" }),
    ).toHaveCount(0);
    expect(calls).toBe(1);
  });
}

test("blocks repeat confirmation and Escape while a publication is pending", async ({
  page,
}) => {
  await signIn(page);
  await page.route("**/api/events", (route) =>
    route.fulfill({ json: [draft] }),
  );
  let release: () => void = () => {};
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  let calls = 0;
  await page.route("**/api/events/event-1/publish", async (route) => {
    calls++;
    await pending;
    await route.fulfill({
      json: {
        ...draft,
        status: "open",
        discord_url: "https://discord.com/channels/guild/channel/message",
      },
    });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Publish to Discord" }).click();
  await page.getByRole("button", { name: "Confirm publication" }).click();
  await expect(
    page.getByRole("button", { name: "Publishing…", exact: true }),
  ).toBeDisabled();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeVisible();
  release();
  await expect(
    page.getByRole("link", { name: /View Discord poll/ }),
  ).toBeVisible();
  expect(calls).toBe(1);
});

test("rejects missing and ambiguous local times around daylight saving changes", async ({
  page,
}) => {
  await signIn(page);
  await page.route("**/api/events", (route) => route.fulfill({ json: [] }));
  await page.goto("/");
  await fillDraft(page);
  await setDateTime(page, "March", "12", "2090", "02", "30", "AM");
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(
    page.getByRole("group", { name: /Event starts/ }),
  ).toHaveAttribute("aria-invalid", "true");
  await expect(page.getByRole("alert")).toContainText("may not exist");
  await setDateTime(page, "November", "5", "2090", "01", "30", "AM");
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByRole("alert")).toContainText("occurs twice");
});

test("edits a draft and requires confirmation before deleting it", async ({
  page,
}) => {
  await signIn(page);
  let current = { ...draft };
  let deletions = 0;
  await page.route("**/api/events", (route) =>
    route.fulfill({ json: [current] }),
  );
  await page.route("**/api/events/event-1", async (route) => {
    expect(route.request().headers()["x-csrf-token"]).toBe(session.csrf);
    if (route.request().method() === "PUT") {
      const body = route.request().postDataJSON();
      current = {
        ...current,
        ...body,
        starts_at: Date.parse(body.starts_at) / 1000,
        opens_at: Date.parse(body.opens_at) / 1000,
        signup_closes_at: Date.parse(body.signup_closes_at) / 1000,
      };
      return route.fulfill({ json: current });
    }
    expect(route.request().method()).toBe("DELETE");
    deletions++;
    return route.fulfill({ status: 204 });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Edit draft", exact: true }).click();
  await expect(page.getByLabel(/Table 1 capacity/)).toHaveValue("15");
  await page.getByLabel(/Event title/).fill("Saturday games");
  await page.getByLabel(/Table 1 capacity/).fill("123");
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Saturday games", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("123 seats", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Delete draft", exact: true }).click();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  expect(deletions).toBe(0);
  await page.getByRole("button", { name: "Delete draft", exact: true }).click();
  await page
    .getByRole("button", { name: "Confirm deletion", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "No events yet" }),
  ).toBeVisible();
  expect(deletions).toBe(1);
});
