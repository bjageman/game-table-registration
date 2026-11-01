import { expect, test } from "@playwright/test";

test("table titles fit beside counts as available width changes", async ({ page }) => {
  const names = ["A Very Long Table Name For Everyone", "Table B", "Another Long Table Name For Testing"];
  await page.route("**/api/me", (route) => route.fulfill({ json: { username: "organizer", csrf: "csrf" } }));
  await page.route("**/api/events", (route) => route.fulfill({ json: [{ id: "event", title: "Game Night", status: "draft", starts_at: 3800000000, duration_hours: 24, closes_at: null, discord_url: null, tables: names.map((name) => ({ name, capacity: 15 })) }] }));
  await page.goto("/");
  await page.getByRole("button", { name: /^Game Night/ }).click();
  const modal = page.getByRole("dialog", { name: "Game Night", exact: true });
  for (const width of [390, 800, 1200]) {
    await page.setViewportSize({ width, height: 900 });
    for (const name of names) {
      const title = modal.getByRole("heading", { name, exact: true });
      await expect.poll(async () => title.evaluate((heading) => {
        const range = document.createRange();
        range.selectNodeContents(heading);
        const count = heading.nextElementSibling!.getBoundingClientRect();
        const rect = heading.getBoundingClientRect();
        return range.getBoundingClientRect().width <= heading.clientWidth + 1 && rect.right <= count.left && getComputedStyle(heading).whiteSpace === "nowrap";
      })).toBe(true);
    }
  }
});
