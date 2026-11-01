import { test, expect } from "@playwright/test";

test.describe("Professor landing page", () => {
  test("shows the product shell and working sign-in navigation", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveTitle(/ClassPart AI/);
    await expect(page.getByRole("heading", { name: "Make every discussion count." })).toBeVisible();
    await expect(page.getByRole("link", { name: "Open workspace" })).toHaveAttribute(
      "href",
      "/dashboard"
    );
    await expect(page.getByRole("link", { name: "Create account" })).toHaveAttribute(
      "href",
      "/signup"
    );
    await expect(page.getByText("Early development", { exact: true })).toBeVisible();
    await page
      .getByRole("navigation", { name: "Main navigation" })
      .getByRole("link", { name: "Sign in", exact: true })
      .click();
    await expect(page).toHaveURL(/\/login$/);
  });

  test("guards the professor workspace and opens account registration", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: "Open workspace", exact: true }).click();
    await expect(page).toHaveURL(/\/login$/);
    await page.goto("/");
    await page.getByRole("link", { name: "Create account", exact: true }).click();
    await expect(page).toHaveURL(/\/signup$/);
  });
});
