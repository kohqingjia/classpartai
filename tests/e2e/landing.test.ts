import { test, expect } from "@playwright/test";

test.describe("Landing Page", () => {
  test("should load landing page and show content", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveURL("http://localhost:3000/");
    await expect(page.getByText("TanStack Start template")).toBeVisible();
    await expect(page.getByRole("link", { name: /get started/i })).toBeVisible();
  });
});
