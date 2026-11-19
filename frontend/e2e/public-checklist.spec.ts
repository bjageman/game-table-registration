import { test, expect } from "./fixtures";

test("public attendance survives reload on desktop and mobile", async ({ page }) => {
  await page.route("**/api/public/events/checklist", route => route.fulfill({ json: {
    title: "Game night", description: "", location: "", starts_at: 2000000000, archived: false,
    tables: [{ name: "Table One", capacity: 2,
      players: [{ id: "alice", name: "Alice with a very long display name" }],
      waitlist: [{ id: "bob", name: "Bob" }] },
      ...["Two", "Three"].map(name => ({ name: `Table ${name}`, capacity: 1,
        players: [{ id: name, name: "Test Player 051" }], waitlist: [] })),
    ],
  } }));
  await page.goto("/#/shared/checklist");
  await expect(page.getByText("Test Player 051", { exact: true })).toHaveCount(2);
  for (const name of await page.getByText("Test Player 051", { exact: true }).all()) {
    await expect(name).toBeVisible();
    expect(await name.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
    expect(await name.evaluate(element => {
      const range = document.createRange();
      range.selectNodeContents(element);
      return range.getClientRects().length;
    })).toBe(1);
  }
  if (page.viewportSize()!.width >= 1024) {
    const cards = await page.locator("#public-event-tables > li").all();
    const boxes = await Promise.all(cards.map(card => card.boundingBox()));
    expect(boxes[0]!.y).toBe(boxes[1]!.y);
    expect(boxes[1]!.y).toBe(boxes[2]!.y);
    expect(boxes[0]!.x).toBeLessThan(boxes[1]!.x);
    expect(boxes[1]!.x).toBeLessThan(boxes[2]!.x);
  }
  await expect(page.getByRole("textbox")).toHaveCount(0);
  const arrived = page.getByRole("checkbox", { name: "Mark Alice with a very long display name as arrived" });
  for (const row of await page.locator(".public-checklist-player").all()) {
    const checkbox = await row.getByRole("checkbox").boundingBox();
    const name = await row.locator(".public-checklist-name > span:last-child").boundingBox();
    expect(checkbox!.x + checkbox!.width).toBeLessThanOrEqual(name!.x);
    expect(checkbox!.y + checkbox!.height / 2).toBeCloseTo(name!.y + name!.height / 2, 0);
  }
  const checkboxBox = await arrived.boundingBox();
  const targetBox = await arrived.locator("..").boundingBox();
  expect(checkboxBox).not.toBeNull();
  expect(targetBox).not.toBeNull();
  expect(checkboxBox!.width).toBeGreaterThanOrEqual(22);
  expect(checkboxBox!.height).toBeGreaterThanOrEqual(22);
  expect(checkboxBox!.x + checkboxBox!.width / 2).toBeCloseTo(targetBox!.x + targetBox!.width / 2, 0);
  expect(checkboxBox!.y + checkboxBox!.height / 2).toBeCloseTo(targetBox!.y + targetBox!.height / 2, 0);
  const playerBox = arrived.locator("xpath=ancestor::label");
  const playerBounds = await playerBox.boundingBox();
  // Press the empty space at the right edge, away from the checkbox and name.
  await playerBox.click({ position: { x: playerBounds!.width - 8, y: playerBounds!.height / 2 } });
  await expect(arrived).toBeChecked();
  await expect(playerBox).toHaveCSS("outline-style", "none");
  await page.getByRole("checkbox", { name: "Mark Bob as arrived" }).check();
  await expect(page.getByText("Alice with a very long display name", { exact: true })).toHaveCSS("text-decoration-line", "line-through");
  await page.reload();
  await expect(arrived).toBeChecked();
  await expect(page.getByRole("checkbox", { name: "Mark Bob as arrived" })).toBeChecked();
  await playerBox.click({ position: { x: playerBounds!.width - 8, y: playerBounds!.height / 2 } });
  await expect(arrived).not.toBeChecked();
  await arrived.focus();
  await page.keyboard.press("Space");
  await expect(arrived).toBeChecked();
  await page.keyboard.press("Space");
  await expect(arrived).not.toBeChecked();
  await expect(page.getByText("Alice with a very long display name", { exact: true })).toHaveCSS("text-decoration-line", "none");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
