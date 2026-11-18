import { test, expect } from "./fixtures";

test("public attendance and notes survive reload on desktop and mobile", async ({ page }) => {
  await page.route("**/api/public/events/checklist", route => route.fulfill({ json: {
    title: "Game night", description: "", location: "", starts_at: 2000000000, archived: false,
    tables: [{ name: "Table One", capacity: 2,
      players: [{ id: "alice", name: "Alice with a very long display name" }],
      waitlist: [{ id: "bob", name: "Bob" }] }],
  } }));
  await page.goto("/#/shared/checklist");
  const arrived = page.getByRole("checkbox", { name: "Mark Alice with a very long display name as arrived" });
  const notes = page.getByRole("textbox", { name: "Notes for Alice with a very long display name" });
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
