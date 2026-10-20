import { test, expect } from "@playwright/test";

import { waitForHydration } from "./hydration";

test.describe("Auth and Notes Lifecycle Loop", () => {
  test("completes signup, login, and note creation/deletion loop", async ({ page }) => {
    const uniqueId = Date.now();
    const testEmail = `e2e-user-${uniqueId}@example.com`;
    const testPassword = "Password123!";
    const noteTitle = `E2E Note ${uniqueId}`;

    async function fillCredentials() {
      await page.locator("#email").fill(testEmail);
      await page.locator("#password").fill(testPassword);
    }

    // 1. Sign up
    await page.goto("/signup");
    await waitForHydration(page);
    await expect(page.getByRole("heading", { name: "Create an account" })).toBeVisible({
      timeout: 10_000,
    });

    await fillCredentials();
    await page.getByRole("button", { name: "Create account" }).click();

    // Verify signup confirmation heading
    await expect(page.getByRole("heading", { name: "Check your email" })).toBeVisible({
      timeout: 10_000,
    });

    // 2. Sign out so we can verify explicit login flow
    await page.getByRole("button", { name: "Sign out" }).click();
    await page.waitForURL("/", { timeout: 10_000 });

    // 3. Sign in via /login
    await page.goto("/login");
    await waitForHydration(page);
    await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible({
      timeout: 10_000,
    });

    await fillCredentials();
    await page.getByRole("button", { name: "Sign in", exact: true }).click();

    // After sign-in, redirect completes to home page
    await page.waitForURL("/", { timeout: 10_000 });

    // 4. Navigate to /dashboard
    await page.goto("/dashboard");
    await waitForHydration(page);
    await expect(page.getByRole("heading", { name: `Welcome, ${testEmail}` })).toBeVisible({
      timeout: 10_000,
    });

    // 5. Create a note
    const noteInput = page.getByPlaceholder("New note title…");
    await noteInput.fill(noteTitle);
    await page.getByRole("button", { name: "Add" }).click();

    // Verify note is rendered in the table
    await expect(page.getByRole("cell", { name: noteTitle, exact: true })).toBeVisible({
      timeout: 10_000,
    });

    // 6. Delete the note
    const deleteButton = page.getByRole("button", { name: `Delete note: ${noteTitle}` });
    await deleteButton.click();

    // Verify note is removed from table
    await expect(page.getByRole("cell", { name: noteTitle, exact: true })).not.toBeVisible({
      timeout: 10_000,
    });
  });
});
