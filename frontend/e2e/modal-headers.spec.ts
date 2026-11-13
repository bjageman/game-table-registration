import { test, expect, type Locator } from "@playwright/test";

async function expectHeaderFits(dialog: Locator) {
  await expect.poll(() => dialog.locator(".event-modal-header").evaluate((header) => {
    const heading = header.querySelector("h2")!;
    const close = header.querySelector<HTMLButtonElement>(":scope > button")!;
    const titleBounds = heading.getBoundingClientRect();
    const closeBounds = close.getBoundingClientRect();
    const badge = header.querySelector<HTMLElement>(":scope > .event-badges, :scope > .badge");
    const badgeBounds = badge?.getBoundingClientRect();
    const badgesSmaller = [...header.querySelectorAll(".badge")].every((item) =>
      parseFloat(getComputedStyle(item).fontSize) < parseFloat(getComputedStyle(heading).fontSize));
    return heading.scrollWidth <= heading.clientWidth + 1
      && badgesSmaller
      && titleBounds.right <= closeBounds.left
      && (!badgeBounds || (titleBounds.right <= badgeBounds.left && badgeBounds.right <= closeBounds.left
        && Math.abs(badgeBounds.y + badgeBounds.height / 2 - closeBounds.y - closeBounds.height / 2) < 1))
      && Math.abs(titleBounds.y + titleBounds.height / 2 - closeBounds.y - closeBounds.height / 2) < 1
      && getComputedStyle(heading).whiteSpace === "nowrap";
  })).toBe(true);
}

for (const title of ["Demo Event Time", "A very long event name that needs to fit the confirmation dialog header without moving its close icon"]) {
  test(`keeps modal titles and close icons on one line: ${title}`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.route("**/api/**", (route) => {
      const path = new URL(route.request().url()).pathname;
      const json = path === "/api/me" ? { username: "organizer", csrf: "csrf" }
        : path === "/api/branding" ? { name: "TableSignup", tagline: "", logo_url: null }
        : path === "/api/events" ? [{ id: "event", title, status: "open", starts_at: 3800000000,
          duration_hours: 24, closes_at: 3799900000, discord_url: "https://discord.com/poll",
          tables: [{ name: "Table A", capacity: 8 }] }]
        : path.endsWith("/signups") ? [{ name: "Table A", players: [] }] : [];
      return route.fulfill({ json });
    });
    await page.goto("/");
    await page.locator("#event-open-event").click();
    const details = page.locator("#event-dialog-event");
    await expectHeaderFits(details);
    await page.locator("#event-close-signups-event").click();
    const confirmation = page.getByRole("dialog", { name: `Close signups for ${title}?`, exact: true });
    await expectHeaderFits(confirmation);
    await expect(confirmation.getByRole("button", { name: "Close dialog" })).toBeVisible();
    await page.setViewportSize({ width: 320, height: 900 });
    await expectHeaderFits(confirmation);
    const narrowSize = await confirmation.locator("h2").evaluate((heading) => parseFloat(getComputedStyle(heading).fontSize));
    await page.setViewportSize({ width: 1280, height: 900 });
    await expectHeaderFits(confirmation);
    const wideSize = await confirmation.locator("h2").evaluate((heading) => parseFloat(getComputedStyle(heading).fontSize));
    expect(wideSize).toBeGreaterThan(narrowSize);
    await confirmation.getByRole("button", { name: "Cancel" }).click();
    await expect(confirmation).not.toBeVisible();
    expect(errors).toEqual([]);
  });
}
