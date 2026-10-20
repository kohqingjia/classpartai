import { test, expect } from "@playwright/test";

test.describe("Dashboard page (Signed Out)", () => {
  test("redirects unauthenticated user to login", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login/);
  });
});
