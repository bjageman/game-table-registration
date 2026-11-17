import { test, expect } from "./fixtures";

test("Connect authorizes, saves the server on return, and saves a channel separately", async ({ page, context, baseURL }) => {
  let selection: { guild_id: string; guild_name: string; channel_id: string; channel_name: string } | null = null;
  let channelSaves = 0;
  let disconnects = 0;
  let authorized = false;
  await page.route("**/api/me", (route) => route.fulfill({ json: {
    username: "organizer", csrf: "csrf", needs_setup: !selection?.channel_id,
    destination: selection ? `${selection.guild_id}:${selection.channel_id}` : "disconnected",
  } }));
  await page.route("**/api/events", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/settings", (route) => {
    if (route.request().method() === "DELETE") {
      expect(route.request().headers()["x-csrf-token"]).toBe("csrf");
      selection = null; disconnects++;
      return route.fulfill({ status: 204 });
    }
    if (route.request().method() === "PUT") {
      expect(route.request().headers()["x-csrf-token"]).toBe("csrf");
      expect(route.request().postDataJSON()).toEqual({ guild_id: "200", channel_id: "201" });
      expect(authorized).toBe(true);
      selection = { guild_id: "200", guild_name: "Chosen Server", channel_id: "201", channel_name: "games" };
      channelSaves++;
      return route.fulfill({ json: selection });
    }
    return route.fulfill({ json: { selection, disconnected: !selection, connect_url: "/api/auth/connect" } });
  });
  await page.route("**/api/settings/channels?*", (route) => {
    expect(new URL(route.request().url()).searchParams.get("guild_id")).toBe("200");
    return route.fulfill({ json: { channels: [{ id: "201", name: "games" }] } });
  });
  await page.route("**/api/settings/assignment", (route) => route.fulfill({ json: { automatic_weight_adjustment: true } }));
  await page.route("**/api/auth/connect", (route) => route.fulfill({ contentType: "text/html", body: `<script>location.replace("https://discord.com/oauth2/authorize?state=connection-state&scope=identify+guilds+bot")</script>` }));
  await page.route("https://discord.com/**", (route) => route.fulfill({ contentType: "text/html", body: `<a href="${baseURL}/api/auth/callback?code=approved&state=connection-state&guild_id=200">Authorize</a>` }));
  await page.route("**/api/auth/callback?*", (route) => {
    authorized = true;
    selection = { guild_id: "200", guild_name: "Chosen Server", channel_id: "", channel_name: "" };
    return route.fulfill({ status: 302, headers: { location: "/#/settings" } });
  });
  await page.goto("/#/settings");
  await expect(page.getByRole("link", { name: "Add TableSignup to Discord" })).toHaveCount(0);
  await expect(page.getByRole("combobox", { name: "Discord Server" })).toHaveCount(0);
  const connect = page.getByRole("link", { name: "Connect", exact: true });
  await page.getByRole("tab", { name: "Connection", exact: true }).click();
  await expect(connect).toHaveAttribute("href", "/api/auth/connect");
  await connect.click();
  await expect(page).toHaveURL(/discord\.com\/oauth2\/authorize/);
  await page.getByRole("link", { name: "Authorize", exact: true }).click();
  await expect(page).toHaveURL(`${baseURL}/#/settings`);
  await page.getByRole("tab", { name: "Connection", exact: true }).click();
  await expect(page.getByRole("button", { name: "Disconnect", exact: true })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Discord Server" })).toHaveText("Chosen Server");
  await expect(page.getByRole("combobox", { name: "Discord Server" })).toHaveAttribute("aria-expanded", "false");
  await expect(connect).toHaveCount(0);
  expect(channelSaves).toBe(0);
  expect(context.pages()).toHaveLength(1);
  await page.reload();
  await page.getByRole("tab", { name: "Connection", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Discord Server" })).toHaveText("Chosen Server");
  await page.getByRole("combobox", { name: "Signup Channel" }).click();
  await page.getByRole("option", { name: "#games" }).click();
  await Promise.all([
    page.waitForResponse((response) => new URL(response.url()).pathname === "/api/settings" && response.request().method() === "PUT" && response.ok()),
    page.getByRole("form", { name: "Connection settings" }).getByRole("button", { name: "Save", exact: true }).click(),
  ]);
  expect(channelSaves).toBe(1);
  await page.reload();
  await page.getByRole("tab", { name: "Connection", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Signup Channel" })).toHaveText("#games");
  const refresh = page.getByRole("button", { name: "Refresh Channels", exact: true });
  const request = page.waitForRequest((r) => r.url().includes("/api/settings/channels?guild_id=200"));
  await refresh.click(); await request;
  await expect(page.getByRole("combobox", { name: "Signup Channel" })).toHaveText("#games");
  const channelBox = await page.getByRole("combobox", { name: "Signup Channel" }).boundingBox();
  const refreshBox = await refresh.boundingBox();
  expect(refreshBox!.x).toBeGreaterThan(channelBox!.x + channelBox!.width);
  expect(Math.abs(refreshBox!.y - channelBox!.y)).toBeLessThanOrEqual(1);
  await page.getByRole("button", { name: "Disconnect", exact: true }).click();
  const confirmation = page.getByRole("dialog", { name: "Disconnect Discord?" });
  await confirmation.getByRole("button", { name: "Cancel", exact: true }).click();
  expect(disconnects).toBe(0);
  await page.getByRole("button", { name: "Disconnect", exact: true }).click();
  await confirmation.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(connect).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Discord Server" })).toHaveCount(0);
  await expect(page.getByRole("combobox", { name: "Signup Channel" })).toHaveCount(0);
  await page.reload();
  await page.getByRole("tab", { name: "Connection", exact: true }).click();
  await expect(connect).toBeVisible();
  expect(disconnects).toBe(1);
});

test("Preferences are accessible after server authorization and persists its setting", async ({ page }) => {
  let enabled = true;
  await page.route("**/api/me", (route) => route.fulfill({ json: { username: "organizer", csrf: "csrf", needs_setup: true } }));
  await page.route("**/api/settings", (route) => route.fulfill({ json: {
    selection: { guild_id: "100", channel_id: "", guild_name: "Server", channel_name: "" }, connect_url: "/api/auth/connect",
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
  await expect(page.getByRole("link", { name: "Game Events", exact: true })).toHaveCount(0);
  await page.getByRole("tab", { name: "Preferences", exact: true }).click();
  const form = page.getByRole("form", { name: "Preferences" });
  const checkbox = form.getByLabel("Automatically Adjust Player Weights");
  await expect(checkbox).toBeChecked();
  await checkbox.uncheck();
  await expect(form.getByRole("status")).toHaveText("Settings saved.");
  await page.reload();
  await page.getByRole("tab", { name: "Preferences", exact: true }).click();
  await expect(checkbox).not.toBeChecked();
  await checkbox.check();
  await expect(form.getByRole("status")).toHaveText("Settings saved.");
  expect(enabled).toBe(true);
  await page.getByRole("tab", { name: "Connection", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Discord Server" })).toBeVisible();
  await expect(form).toBeHidden();
  await page.getByRole("tab", { name: "Connection", exact: true }).focus();
  await page.keyboard.press("ArrowLeft"); await page.keyboard.press("Enter");
  await expect(checkbox).toBeChecked();
});

test("settings use the full page with ordered preferences and an inline organization selector", async ({ page }) => {
  await page.route("**/api/me", route => route.fulfill({ json: { username: "organizer", csrf: "csrf", user_id: "owner" } }));
  await page.route("**/api/settings", route => route.fulfill({ json: { selection: null } }));
  await page.route("**/api/organizations", route => route.fulfill({ json: {
    selected_id: "org", organizations: [{ id: "org", name: "Friday Crew", created_by: "owner", role: "admin" }],
  } }));
  await page.route("**/api/organizations/org/members", route => route.fulfill({ json: [] }));
  await page.goto("/#/settings");
  const tabs = page.getByRole("tab");
  await expect(tabs).toHaveText(["Preferences", "Connection", "Organization"]);
  await expect(tabs.first()).toHaveAttribute("aria-selected", "true");
  await expect(page.locator("#settings-panel")).toHaveCount(0);
  const form = page.getByRole("form", { name: "Preferences" });
  const playerManagement = form.getByRole("region", { name: "Player Management" });
  const discord = form.getByRole("region", { name: "Discord", exact: true });
  await expect(playerManagement.getByRole("checkbox", { name: "Automatically Adjust Player Weights" })).toBeVisible();
  await expect(playerManagement.getByRole("checkbox", { name: "Waitlisted players will be guaranteed a seat for the next event" })).toBeVisible();
  await expect(discord.getByRole("checkbox", { name: "Review assignments before sending", exact: true })).toBeVisible();
  await expect(discord.getByRole("checkbox", { name: "Announce table changes" })).toBeVisible();
  const timezone = await form.getByRole("combobox", { name: "Timezone" }).boundingBox();
  const playersHeading = await playerManagement.getByRole("heading").boundingBox();
  const discordHeading = await discord.getByRole("heading").boundingBox();
  expect(timezone!.y + timezone!.height).toBeLessThan(playersHeading!.y);
  expect(playersHeading!.y).toBeLessThan(discordHeading!.y);
  const main = await page.getByRole("main").boundingBox();
  const panel = await page.getByRole("tabpanel", { name: "Preferences" }).boundingBox();
  expect(panel!.width).toBeCloseTo(main!.width, 0);
  await page.getByRole("tab", { name: "Organization" }).click();
  const selection = page.getByRole("combobox", { name: "Active Organization:" });
  await expect(selection).toHaveValue("org");
  const label = await page.getByText("Active Organization:", { exact: true }).boundingBox();
  const dropdown = await selection.boundingBox();
  expect(label!.x + label!.width).toBeLessThan(dropdown!.x);
  expect(Math.abs(label!.y + label!.height / 2 - dropdown!.y - dropdown!.height / 2)).toBeLessThan(2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
