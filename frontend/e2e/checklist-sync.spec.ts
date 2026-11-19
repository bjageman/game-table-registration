import { test, expect, type Page } from "./fixtures";

interface Server { revision: number; entries: Record<string, boolean>; failWrite: boolean; failRead: boolean; conflictNext: boolean; writes: number; delayWrite?: Promise<void> }
async function mockChecklist(page: Page, server: Server) {
  await page.route(/\/api\/public\/events\/sync(?:\/checklist)?$/, async route => {
    if (!new URL(route.request().url()).pathname.endsWith("/checklist")) return route.fulfill({ json: {
      title: "Shared game", description: "", location: "", starts_at: 2000000000, archived: false,
      tables: [{ name: "One", capacity: 2, players: [{ id: "alice", name: "Alice" }, { id: "bob", name: "Bob" }], waitlist: [] }],
    } });
    const method = route.request().method();
    if (method === "GET" && server.failRead) return route.fulfill({ status: 503, json: { detail: "Storage unavailable" } });
    if (method !== "GET") {
      server.writes++;
      await server.delayWrite;
      if (server.failWrite) return route.fulfill({ status: 503, json: { detail: "Storage unavailable" } });
      const body = route.request().postDataJSON();
      if (method === "PUT" && (server.conflictNext || body.revision !== server.revision)) {
        server.conflictNext = false; server.revision++;
        server.entries.bob = true;
        return route.fulfill({ status: 409, json: { detail: "Changed" } });
      }
      if (method === "PATCH") server.entries[body.player_id] = body.arrived;
      else server.entries = body.entries;
      server.revision++;
    }
    return route.fulfill({ json: { revision: server.revision, entries: server.entries } });
  });
}
function freshServer(): Server {
  return { revision: 0, entries: { alice: false, bob: false }, failWrite: false, failRead: false, conflictNext: false, writes: 0 };
}
const syncToggle = (page: Page) => page.getByRole("checkbox", { name: "Sync with Server", exact: true });
const alice = (page: Page) => page.getByRole("checkbox", { name: "Mark Alice as arrived" });
const bob = (page: Page) => page.getByRole("checkbox", { name: "Mark Bob as arrived" });

async function open(page: Page, server: Server) {
  await mockChecklist(page, server);
  await page.goto("/#/shared/sync");
  await expect(alice(page)).toBeEnabled();
}

test("sync defaults on, starts with the server version, and propagates between viewers", async ({ page, browser }) => {
  const server = freshServer();
  await page.addInitScript(() => localStorage.setItem("public-event-checklist:sync", JSON.stringify({ alice: { arrived: true } })));
  await open(page, server);
  await expect(syncToggle(page)).toBeChecked();
  await expect(alice(page)).not.toBeChecked();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const context = await browser.newContext();
  const other = await context.newPage();
  await open(other, server);
  await alice(page).check();
  await expect(alice(other)).toBeChecked({ timeout: 7000 });
  await expect(alice(other)).toBeEnabled();
  await bob(other).check();
  await expect(bob(page)).toBeChecked({ timeout: 7000 });
  expect(server.entries).toEqual({ alice: true, bob: true });
  await context.close();
});

for (const side of ["browser", "server"]) {
  test(`reconnecting lets the user choose the ${side} version`, async ({ page }) => {
    const server = freshServer();
    await open(page, server);
    await syncToggle(page).uncheck();
    await alice(page).check();
    expect(server.entries.alice).toBe(false);
    expect(server.writes).toBe(0);
    // Server changes while this viewer is working locally must not erase edits.
    server.entries.bob = true; server.revision++;
    await page.reload();
    await expect(syncToggle(page)).not.toBeChecked();
    await expect(alice(page)).toBeChecked();
    await expect(bob(page)).not.toBeChecked();
    await syncToggle(page).check();
    const dialog = page.getByRole("dialog", { name: "Choose checklist version" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText("Use the browser version to replace", { exact: false })).toHaveCount(0);
    const buttons = await dialog.getByRole("button").all();
    const boxes = await Promise.all(buttons.map(button => button.boundingBox()));
    expect(boxes[0]!.y).toBe(boxes[1]!.y);
    expect(boxes[1]!.y).toBe(boxes[2]!.y);
    expect(boxes[2]!.x + boxes[2]!.width).toBeLessThanOrEqual((await dialog.boundingBox())!.x + (await dialog.boundingBox())!.width);
    await dialog.getByRole("button", { name: side === "browser" ? "Browser" : "Server", exact: true }).click();
    await expect(dialog).not.toBeVisible();
    await expect(syncToggle(page)).toBeChecked();
    await expect(alice(page)).toBeChecked({ checked: side === "browser" });
    await expect(bob(page)).toBeChecked({ checked: side === "server" });
    expect(server.entries).toEqual(side === "browser" ? { alice: true, bob: false } : { alice: false, bob: true });
  });
}

test("identical versions reconnect without a modal and cancelling differences keeps sync off", async ({ page }) => {
  const server = freshServer();
  await open(page, server);
  await syncToggle(page).uncheck();
  await syncToggle(page).check();
  await expect(alice(page)).toBeEnabled();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await syncToggle(page).uncheck();
  await alice(page).check();
  await syncToggle(page).check();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(syncToggle(page)).not.toBeChecked();
  await expect(alice(page)).toBeChecked();
  expect(server.entries.alice).toBe(false);
});

test("a newer server edit blocks stale replacement and asks again", async ({ page }) => {
  const server = freshServer();
  await open(page, server);
  await syncToggle(page).uncheck();
  await alice(page).check();
  await syncToggle(page).check();
  server.conflictNext = true;
  const dialog = page.getByRole("dialog", { name: "Choose checklist version" });
  await dialog.getByRole("button", { name: "Browser", exact: true }).click();
  await expect(dialog.getByRole("alert")).toContainText("server checklist changed");
  expect(server.entries).toEqual({ alice: false, bob: true });
  await dialog.getByRole("button", { name: "Server", exact: true }).click();
  await expect(alice(page)).not.toBeChecked();
  await expect(bob(page)).toBeChecked();
});

test("failed writes keep browser changes and turn sync off until reconciled", async ({ page }) => {
  const server = freshServer();
  await open(page, server);
  server.failWrite = true;
  await alice(page).check();
  await expect(syncToggle(page)).not.toBeChecked();
  await expect(page.getByRole("alert")).toContainText("change could not be confirmed");
  await expect(alice(page)).toBeChecked();
  expect(server.entries.alice).toBe(false);
  server.failWrite = false;
  await syncToggle(page).check();
  await page.getByRole("button", { name: "Browser", exact: true }).click();
  await expect(alice(page)).toBeEnabled();
  expect(server.entries.alice).toBe(true);
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("an unavailable server on first load preserves the browser checklist without uploading it", async ({ page }) => {
  const server = freshServer();
  server.failRead = true;
  await page.addInitScript(() => localStorage.setItem("public-event-checklist:sync", JSON.stringify({ alice: { arrived: true } })));
  await open(page, server);
  await expect(syncToggle(page)).not.toBeChecked();
  await expect(alice(page)).toBeChecked();
  await expect(page.getByRole("alert")).toContainText("Could not refresh");
  expect(server.writes).toBe(0);
  server.failRead = false;
  await syncToggle(page).check();
  await expect(page.getByRole("dialog", { name: "Choose checklist version" })).toBeVisible();
});

test("a failed browser replacement keeps the modal and can be retried explicitly", async ({ page }) => {
  const server = freshServer();
  await open(page, server);
  await syncToggle(page).uncheck();
  await alice(page).check();
  await syncToggle(page).check();
  server.failWrite = true;
  const dialog = page.getByRole("dialog", { name: "Choose checklist version" });
  await dialog.getByRole("button", { name: "Browser", exact: true }).click();
  await expect(dialog.getByRole("alert")).toContainText("Storage unavailable");
  expect(server.entries.alice).toBe(false);
  server.failWrite = false;
  await dialog.getByRole("button", { name: "Browser", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  expect(server.entries.alice).toBe(true);
});

test("rapid selections stay steady and all save in order while the server is slow", async ({ page }) => {
  const server = freshServer();
  let release!: () => void;
  server.delayWrite = new Promise<void>(resolve => { release = resolve; });
  await open(page, server);
  const row = alice(page).locator("xpath=ancestor::label");
  const before = await row.boundingBox();
  await alice(page).check();
  await expect(alice(page)).toBeEnabled();
  await expect(row).toHaveCSS("opacity", "1");
  await bob(page).check();
  await alice(page).uncheck();
  await expect(bob(page)).toBeChecked();
  await expect(alice(page)).not.toBeChecked();
  await expect(page.getByText("Syncing…", { exact: true })).toHaveCount(0);
  expect(await row.boundingBox()).toEqual(before);
  release();
  await expect.poll(() => server.writes).toBe(3);
  await expect.poll(() => server.entries).toEqual({ alice: false, bob: true });
  await expect(syncToggle(page)).toBeEnabled();
  await expect(alice(page)).not.toBeChecked();
  await expect(bob(page)).toBeChecked();
});
