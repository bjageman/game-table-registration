import { test, expect } from "./fixtures";

test("public attendance and notes survive reload on desktop and mobile", async ({ page }) => {
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
    expect(await name.evaluate(element => {
      const range = document.createRange();
      range.selectNodeContents(element);
      return range.getClientRects().length;
    })).toBe(1);
  }
  const arrived = page.getByRole("checkbox", { name: "Mark Alice with a very long display name as arrived" });
  const notes = page.getByRole("textbox", { name: "Notes for Alice with a very long display name" });
  const checkboxBox = await arrived.boundingBox();
  const targetBox = await arrived.locator("..").boundingBox();
  expect(checkboxBox).not.toBeNull();
  expect(targetBox).not.toBeNull();
  expect(checkboxBox!.width).toBeGreaterThanOrEqual(22);
  expect(checkboxBox!.height).toBeGreaterThanOrEqual(22);
  expect(checkboxBox!.x + checkboxBox!.width / 2).toBeCloseTo(targetBox!.x + targetBox!.width / 2, 0);
  expect(checkboxBox!.y + checkboxBox!.height / 2).toBeCloseTo(targetBox!.y + targetBox!.height / 2, 0);
  await arrived.check();
  await notes.fill("Bringing snacks");
  await page.getByRole("checkbox", { name: "Mark Bob as arrived" }).check();
  await expect(page.getByText("Alice with a very long display name", { exact: true })).toHaveCSS("text-decoration-line", "line-through");
  await page.reload();
  await expect(arrived).toBeChecked();
  await expect(notes).toHaveValue("Bringing snacks");
  await expect(page.getByRole("checkbox", { name: "Mark Bob as arrived" })).toBeChecked();
  await arrived.uncheck();
  await expect(page.getByText("Alice with a very long display name", { exact: true })).toHaveCSS("text-decoration-line", "none");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
