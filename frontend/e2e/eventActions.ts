import { expect, type Page } from "./fixtures";

export async function openEvent(page: Page, id = "event-1") {
  await page.locator(`#event-open-${id}`).click();
  const dialog = page.locator(`#event-dialog-${id}`);
  await expect(dialog).toBeVisible();
  return dialog;
}
