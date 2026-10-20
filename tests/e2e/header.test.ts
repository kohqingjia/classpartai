import { randomUUID } from "node:crypto";
import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";

import { waitForHydration } from "./hydration";

const password = "HeaderSession123!";

async function signUp(page: Page): Promise<void> {
  const response = await page.request.post("/api/auth/sign-up/email", {
    data: {
      name: "Header visitor",
      email: `header-${randomUUID()}@example.invalid`,
      password,
    },
  });
  expect(response.ok(), await response.text()).toBe(true);
}

/**
 * The nav is server-rendered from the session the request already carries.
 *
 * `page.request.get` is the assertion that matters — it reads the server's own response, before
 * a line of client JavaScript runs. Asking the rendered page instead would pass just as well
 * against the `authClient.useSession()` the header used to call, which only answers after
 * hydration and made "Sign out" pop into a nav that had already painted without it.
 */
test.describe("Header session", () => {
  test("serves the signed-in nav in the server markup", async ({ page }) => {
    await signUp(page);

    // `/dashboard` sits under `_authenticated`; `/` does not, so only `__root.tsx` can supply
    // the user there — the header has to work on both.
    const [dashboard, landing] = await Promise.all(
      ["/dashboard", "/"].map(url => page.request.get(url))
    );
    expect(dashboard.ok()).toBe(true);
    expect(landing.ok()).toBe(true);
    expect(await dashboard.text()).toContain("Sign out");
    expect(await landing.text()).toContain("Sign out");
  });

  test("leaves it out for a visitor with no session", async ({ page }) => {
    const response = await page.request.get("/");
    expect(response.ok()).toBe(true);
    expect(await response.text()).not.toContain("Sign out");
  });

  test("hydrates the signed-in nav without a mismatch", async ({ page }) => {
    await signUp(page);

    const mismatches: string[] = [];
    page.on("console", message => {
      if (/hydrat|did not match|server[- ]rendered HTML/i.test(message.text())) {
        mismatches.push(message.text());
      }
    });
    page.on("pageerror", error => {
      if (/hydrat/i.test(error.message)) {
        mismatches.push(error.message);
      }
    });

    await page.goto("/dashboard");
    await waitForHydration(page);

    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
    expect(mismatches).toEqual([]);
  });
});
