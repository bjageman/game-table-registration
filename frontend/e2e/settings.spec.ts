import { test, expect } from "@playwright/test";

for (const newUser of [false, true]) {
  test(`configures a Discord destination from Settings (new user: ${newUser})`, async ({ page }) => {
    let selected = { guild_id: "100", channel_id: "101", guild_name: "First Server", channel_name: "first" };
    let configured = !newUser;
    await page.route("**/api/me", (route) => route.fulfill({ json: {
      username: "organizer", csrf: "csrf", needs_setup: !configured,
      destination: configured ? `${selected.guild_id}:${selected.channel_id}` : "legacy",
    } }));
    await page.route("**/api/events", (route) => route.fulfill({ json: [] }));
    await page.route("**/api/settings", async (route) => {
      if (route.request().method() === "PUT") {
        expect(route.request().headers()["x-csrf-token"]).toBe("csrf");
        expect(route.request().postDataJSON()).toEqual({ guild_id: "200", channel_id: "201" });
        selected = { guild_id: "200", channel_id: "201", guild_name: "Second Server", channel_name: "games" };
        configured = true;
        return route.fulfill({ json: selected });
      }
      return route.fulfill({ json: {
        selection: configured ? selected : null,
        guilds: [{ id: "100", name: "First Server" }, { id: "200", name: "Second Server" }],
        install_url: "https://discord.com/oauth2/authorize?client_id=client&scope=bot&permissions=562949953489920",
      } });
    });
    await page.route("**/api/settings/channels?*", (route) => route.fulfill({ json: {
      channels: new URL(route.request().url()).searchParams.get("guild_id") === "200"
        ? [{ id: "201", name: "games" }] : [{ id: "101", name: "first" }],
    } }));
    await page.goto("/");
    if (!newUser) {
      await page.getByRole("button", { name: "organizer" }).click();
      await page.getByRole("menuitem", { name: "Settings" }).click();
    }
    await expect(page.getByRole("heading", { name: "Settings", exact: true })).toBeVisible();
    await page.getByRole("combobox", { name: "Discord Server" }).click();
    await page.getByRole("option", { name: "Second Server" }).click();
    await expect(page.getByRole("link", { name: /Add Gather to Discord/ })).toHaveAttribute("href", /guild_id=200/);
    await page.getByRole("combobox", { name: "Signup Channel" }).click();
    await page.getByRole("option", { name: "#games" }).click();
    await page.getByRole("button", { name: "Save", exact: true }).click();
    if (newUser) {
      await expect(page.getByRole("heading", { name: "Game Events", exact: true })).toBeVisible();
      await page.getByRole("button", { name: "organizer" }).click();
      await page.getByRole("menuitem", { name: "Settings" }).click();
    } else {
      await expect(page.getByRole("status")).toHaveText("Settings saved.");
      await page.reload();
    }
    await expect(page.getByRole("combobox", { name: "Discord Server" })).toHaveText("Second Server");
    await expect(page.getByRole("combobox", { name: "Signup Channel" })).toHaveText("#games");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
