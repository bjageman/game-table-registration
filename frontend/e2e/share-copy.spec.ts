import { test, expect } from "./fixtures";

for (const clipboard of ["unavailable", "blocked"]) {
  test(`copies a public link when clipboard access is ${clipboard}`, async ({ page }) => {
    await page.addInitScript(mode => {
      Object.defineProperty(navigator, "clipboard", { configurable: true,
        value: mode === "unavailable" ? undefined : { writeText: () => Promise.reject(new Error("Blocked")) } });
      document.addEventListener("copy", () => {
        const input = document.activeElement;
        if (input instanceof HTMLInputElement) {
          sessionStorage.setItem("copied-public-link", input.value.slice(input.selectionStart ?? 0, input.selectionEnd ?? 0));
        }
      });
    }, clipboard);
    await page.route("**/api/**", route => {
      const path = new URL(route.request().url()).pathname;
      const json = path === "/api/me" ? { username: "organizer", csrf: "csrf" }
        : path === "/api/events" ? [{ id: "event", title: "Shared event", status: "assigned", starts_at: 3800000000,
          duration_hours: 24, closes_at: 3799900000, tables: [{ name: "One", capacity: 2 }] }]
        : path === "/api/events/event/share" ? { path: "/#/shared/test-token" }
        : path.endsWith("/signups") ? []
        : path.endsWith("/announcement") ? { status: "sent", error: null, url: "https://discord.com/announcement" }
        : undefined;
      return json === undefined ? route.fallback() : route.fulfill({ json });
    });
    await page.goto("/");
    await page.locator("#event-open-event").click();
    await page.getByRole("button", { name: "Share event", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Share table assignments" });
    const link = dialog.getByRole("textbox", { name: "Public link" });
    await expect(link).toHaveValue(/\/#\/shared\/test-token$/);
    await dialog.getByRole("button", { name: "Copy link" }).click();
    await expect(dialog.getByRole("button", { name: "Copied", exact: true })).toBeVisible();
    expect(await page.evaluate(() => sessionStorage.getItem("copied-public-link"))).toBe(await link.inputValue());
    await expect(dialog.getByRole("alert")).toHaveCount(0);
  });
}
