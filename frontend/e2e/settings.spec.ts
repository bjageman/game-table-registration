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
    await page.route("**/api/settings/assignment", (route) => route.fulfill({ json: { automatic_weight_adjustment: true } }));
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
    await expect(page.getByText("Choose a server you manage and the channel where TableSignup should post signups.", { exact: true })).toHaveCount(0);
    if (!newUser) await expect(page.getByRole("link", { name: /Add TableSignup to Discord/ })).toHaveCount(0);
    await page.getByRole("combobox", { name: "Discord Server" }).click();
    await page.getByRole("option", { name: "Second Server" }).click();
    await expect(page.getByRole("link", { name: /Add TableSignup to Discord/ })).toHaveAttribute("href", /guild_id=200/);
    await page.getByRole("combobox", { name: "Signup Channel" }).click();
    await page.getByRole("option", { name: "#games" }).click();
    await page.getByRole("form", { name: "Discord settings" }).getByRole("button", { name: "Save", exact: true }).click();
    if (newUser) {
      await expect(page.getByRole("heading", { name: "Game Events", exact: true })).toBeVisible();
      await page.getByRole("button", { name: "organizer" }).click();
      await page.getByRole("menuitem", { name: "Settings" }).click();
    } else {
      await expect(page.getByText("Settings saved.", { exact: true })).toBeVisible();
      await page.reload();
    }
    await expect(page.getByRole("combobox", { name: "Discord Server" })).toHaveText("Second Server");
    await expect(page.getByRole("combobox", { name: "Signup Channel" })).toHaveText("#games");
    await expect(page.getByRole("link", { name: /Add TableSignup to Discord/ })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}


test("persists automatic weight adjustment on and off in Settings", async ({ page }) => {
  let enabled = true;
  await page.route("**/api/me", (route) => route.fulfill({ json: { username: "organizer", csrf: "csrf" } }));
  await page.route("**/api/events", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/settings", (route) => route.fulfill({ json: {
    selection: { guild_id: "100", channel_id: "101", guild_name: "Server", channel_name: "games" },
    guilds: [{ id: "100", name: "Server" }], install_url: "https://discord.com/oauth2/authorize?client_id=client",
  } }));
  await page.route("**/api/settings/channels?*", (route) => route.fulfill({ json: { channels: [{ id: "101", name: "games" }] } }));
  await page.route("**/api/settings/assignment", (route) => {
    if (route.request().method() === "PUT") {
      expect(route.request().headers()["x-csrf-token"]).toBe("csrf");
      enabled = route.request().postDataJSON().automatic_weight_adjustment;
    }
    return route.fulfill({ json: { automatic_weight_adjustment: enabled } });
  });
  await page.goto("/#/settings");
  await expect(page.getByRole("tab", { name: "Discord", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("link", { name: "Game Events", exact: true })).toHaveCount(0);
  await page.getByRole("tab", { name: "Assignments", exact: true }).click();
  await expect(page.getByRole("tabpanel", { name: "Discord", exact: true })).toHaveCount(0);
  const form = page.getByRole("form", { name: "Assignment settings" });
  const checkbox = form.getByLabel("Automatically Adjust Player Weights");
  await expect(checkbox).toBeChecked();
  await checkbox.uncheck();
  await form.getByRole("button", { name: "Save", exact: true }).click();
  await expect(form.getByRole("status")).toHaveText("Assignment settings saved.");
  expect(enabled).toBe(false);
  await page.reload();
  await page.getByRole("tab", { name: "Assignments", exact: true }).click();
  await expect(checkbox).not.toBeChecked();
  await checkbox.check();
  await form.getByRole("button", { name: "Save", exact: true }).click();
  await expect(form.getByRole("status")).toHaveText("Assignment settings saved.");
  expect(enabled).toBe(true);
  await page.getByRole("tab", { name: "Discord", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Discord Server" })).toBeVisible();
  await expect(form).toBeHidden();
  // Arrow-key navigation activates the other tab without losing saved state.
  await page.getByRole("tab", { name: "Discord", exact: true }).focus();
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Enter");
  await expect(checkbox).toBeChecked();
});

test("disconnects only after confirmation and offers setup again", async ({ page }) => {
  let connected = true;
  let disconnects = 0;
  await page.route("**/api/me", (route) => route.fulfill({ json: { username: "organizer", csrf: "csrf", needs_setup: !connected, destination: connected ? "100:101" : "disconnected" } }));
  await page.route("**/api/events", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/settings", (route) => {
    if (route.request().method() === "DELETE") {
      expect(route.request().headers()["x-csrf-token"]).toBe("csrf");
      connected = false; disconnects++;
      return route.fulfill({ status: 204 });
    }
    return route.fulfill({ json: { selection: connected ? { guild_id: "100", channel_id: "101", guild_name: "Server", channel_name: "games" } : null,
      guilds: [{ id: "100", name: "Server" }], install_url: "https://discord.com/oauth2/authorize?client_id=client" } });
  });
  await page.route("**/api/settings/channels?*", (route) => route.fulfill({ json: { channels: [{ id: "101", name: "games" }] } }));
  await page.route("**/api/settings/assignment", (route) => route.fulfill({ json: { automatic_weight_adjustment: true } }));
  await page.goto("/#/settings");
  await page.getByRole("button", { name: "Disconnect", exact: true }).click();
  const confirmation = page.getByRole("dialog", { name: "Disconnect Discord?" });
  await confirmation.getByRole("button", { name: "Cancel", exact: true }).click();
  expect(disconnects).toBe(0);
  await page.getByRole("button", { name: "Disconnect", exact: true }).click();
  await confirmation.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(confirmation).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Disconnect", exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: /Add TableSignup to Discord/ })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Assignments", exact: true })).toBeDisabled();
  await page.reload();
  await expect(page.getByRole("link", { name: /Add TableSignup to Discord/ })).toBeVisible();
  expect(disconnects).toBe(1);
});
