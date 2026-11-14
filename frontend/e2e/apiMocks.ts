import type { Page } from "@playwright/test";

/** Register before feature routes so every API request stays inside the fixture. */
export async function mockApiDefaults(page: Page) {
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    const defaults: Record<string, unknown> = {
      "/api/branding": { name: "TableSignup", tagline: "", logo_url: null },
      "/api/setup": { configured: true },
      "/api/recurring-series": [],
      "/api/templates": [],
      "/api/settings/guilds": { guilds: [{ id: "100", name: "Server" }, { id: "200", name: "Chosen Server" }] },
    };
    if (route.request().method() === "GET" && /^\/api\/events\/[^/]+\/signups$/.test(path)) {
      return route.fulfill({ json: [] });
    }
    if (route.request().method() !== "GET" || !(path in defaults)) throw new Error(`Missing API mock: ${route.request().method()} ${path}`);
    return route.fulfill({ json: defaults[path] });
  });
}
