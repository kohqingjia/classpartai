import { expect } from "@playwright/test";
import type { Page } from "@playwright/test";

/**
 * Waits for React to attach, via the root route's hydration effect. Use it before typing into a
 * controlled input or clicking server-rendered markup, where an action that lands on inert HTML is
 * silently discarded. For a page whose next step is just an assertion, assert on that element
 * directly instead — Playwright auto-waits, and network silence is not a hydration signal.
 */
export async function waitForHydration(page: Page): Promise<void> {
  await expect(page.locator("body")).toHaveAttribute("data-hydrated", "true");
}
