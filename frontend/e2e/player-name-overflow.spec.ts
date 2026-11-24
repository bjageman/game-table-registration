import { test, expect, type Locator, type Page } from "./fixtures";

const longName = "A player with an exceptionally long display name ".repeat(5).trim();
const otherName = `Another ${longName}`;
const availableName = `Available ${longName}`;
const nameFor = (id: string) => id === "1" ? longName : id === "2" ? otherName : availableName;
const profile = (id: string) => ({ discord_id: id, discord_name: nameFor(id),
  real_name: nameFor(id), weighting: 5, guaranteed_seat: false, is_test: false,
  partner: id === "1" ? { id: "2", name: otherName } : null });

async function setup(page: Page, status = "assigned", readOnly = false) {
  await page.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    const json = path === "/api/me" ? { username: longName, csrf: "csrf", ...(readOnly ? { organization_role: "user" } : {}) }
      : path === "/api/events" ? [{ id: "event", title: "Game night", status, starts_at: 3800000000,
        duration_hours: 24, closes_at: 3799900000, tables: [{ name: "Table A", capacity: 2 }] }]
      : path.endsWith("/signups") ? [{ name: "Table A", players: [{ id: "1", name: longName }], waitlist: [{ id: "2", name: otherName }] }]
      : path.endsWith("/announcement") ? { status: "sent", error: null, url: "https://discord.com/announcement" }
      : path === "/api/players" ? [profile("1"), profile("2"), profile("3")]
      : /^\/api\/players\/\d+$/.test(path) ? profile(path.split("/").at(-1)!) : undefined;
    return json === undefined ? route.fallback() : route.fulfill({ json });
  });
}

async function expectTruncated(locator: Locator, fullName: string) {
  await expect(locator).toHaveText(fullName);
  await expect(locator).toHaveAttribute("title", fullName);
  await expect(locator).toHaveCSS("text-overflow", "ellipsis");
  await expect(locator).toHaveCSS("white-space", "nowrap");
  expect(await locator.evaluate(element => element.scrollWidth > element.clientWidth)).toBe(true);
}

for (const status of ["open", "review", "assigned"]) {
  test(`long ${status} roster names stay in their column and remain actionable`, async ({ page }) => {
    await setup(page, status);
    await page.goto("/");
    const accountName = page.locator("#profile-menu-button .truncate-name");
    if (await accountName.isVisible()) await expectTruncated(accountName, longName);
    await page.locator("#event-open-event").click();
    const player = page.locator('button[id$="-player-profile-1"]');
    await expect(player).toBeVisible();
    await expectTruncated(player, longName);
    if (status !== "open") {
      await expectTruncated(page.locator('button[id$="-waitlist-profile-2"]'), otherName);
      await expect(page.getByRole("button", { name: `Swap ${longName} at Table A`, exact: true })).toBeVisible();
    }
    await player.click();
    const dialog = page.getByRole("dialog", { name: "Player Information" });
    await expectTruncated(dialog.locator(".player-discord-name dd"), longName);
    await expect(dialog.getByRole("textbox", { name: "Display Name", exact: true })).toHaveValue(longName);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });
}

test("lookup columns and linked-player options truncate without shortening names or search", async ({ page }) => {
  await setup(page);
  await page.goto("/#/players");
  const row = page.locator("#player-open-1");
  await expectTruncated(row.locator(".player-lookup-username"), longName);
  await expectTruncated(row.locator(".player-lookup-display-name"), longName);
  await expectTruncated(row.locator(".player-lookup-partner"), otherName);
  await row.click();
  const linked = page.getByRole("combobox", { name: "Linked Player" });
  await linked.fill("Another");
  const option = page.getByRole("option", { name: `${otherName} (2)`, exact: true });
  await expectTruncated(option.locator(".truncate-name"), `${otherName} (2)`);
});

test("swap and add-player results keep full names accessible inside truncated rows", async ({ page }) => {
  await setup(page);
  await page.goto("/");
  await page.locator("#event-open-event").click();
  await page.getByRole("button", { name: `Swap ${longName} at Table A`, exact: true }).click();
  const swap = page.getByRole("dialog", { name: `Swap ${longName}`, exact: true });
  await expectTruncated(swap.locator("h2"), `Swap ${longName}`);
  await expectTruncated(swap.locator(".add-player-results strong"), otherName);
  await swap.getByRole("button", { name: "Cancel", exact: true }).click();
  await page.getByRole("button", { name: "Add Player", exact: true }).click();
  const add = page.getByRole("dialog", { name: "Add a player to Table A", exact: true });
  await add.getByRole("combobox", { name: "Search players" }).fill("Available");
  await expectTruncated(add.locator(".add-player-results strong"), availableName);
  await expect(add.locator(".add-player-results button")).toHaveAccessibleName(`${availableName} @${availableName} · 3`);
});

test("read-only assignment and waitlist names use the available row width", async ({ page }) => {
  await setup(page, "assigned", true);
  await page.goto("/");
  await page.locator("#event-open-event").click();
  const seated = page.locator(".table-assigned-player > .truncate-name");
  const waiting = page.locator(".table-waitlist li > .truncate-name");
  await expectTruncated(seated, longName);
  await expectTruncated(waiting, otherName);
  expect((await waiting.boundingBox())!.width).toBeGreaterThan(100);
  await expect(page.getByRole("button", { name: `Swap ${longName} at Table A`, exact: true })).toHaveCount(0);
});
