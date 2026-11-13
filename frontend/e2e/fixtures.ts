import { test as base, expect } from "@playwright/test";
import { mockApiDefaults } from "./apiMocks";

export const test = base.extend({
  page: async ({ page }, runTest) => {
    await mockApiDefaults(page);
    await runTest(page);
  },
});
export { expect };
export type { Page, Locator } from "@playwright/test";
