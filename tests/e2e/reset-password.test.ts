// oxlint-disable node/no-process-env, no-await-in-loop
import { test, expect } from "@playwright/test";

import { waitForHydration } from "./hydration";

const MAILPIT_URL = process.env.MAILPIT_URL ?? "http://localhost:8025";
const password = "Password123!";

test.describe("Reset password", () => {
  test("plain visit asks for an email address", async ({ page }) => {
    await page.goto("/reset-password");
    await expect(page.getByRole("heading", { name: "Reset your password" })).toBeVisible();
    await expect(page.getByLabel(/email/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /send reset link/i })).toBeVisible();
  });

  test("emailed link with a token asks for a new password", async ({ page }) => {
    await page.goto("/reset-password?token=smoke-test-token");
    await expect(page.getByRole("heading", { name: "Set a new password" })).toBeVisible();
    await expect(page.getByLabel(/new password/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /save password/i })).toBeVisible();
  });

  test("stale link explains itself and offers a new one", async ({ page }) => {
    await page.goto("/reset-password?error=INVALID_TOKEN");
    await expect(page.getByText(/invalid or has expired/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /send reset link/i })).toBeVisible();
  });

  test("login page links here", async ({ page }) => {
    await page.goto("/login");
    await page.getByRole("link", { name: /forgot your password/i }).click();
    await expect(page).toHaveURL(/\/reset-password/);
  });
});

/**
 * The account-recovery loop no static render state can prove: request a reset, read the token out
 * of the captured email, set a new password with it, then sign in with that password. Mailpit
 * stands in for the mail provider so the token is real; without it the suite could only assert
 * the form again.
 */
test.describe("Reset password journey", () => {
  const newPassword = "NewPassword456!";

  test("sets a new password from the emailed token and signs in with it", async ({ page }) => {
    const email = `e2e-reset-${Date.now()}@example.com`;

    const signUp = await page.request.post("/api/auth/sign-up/email", {
      headers: { Origin: "http://localhost:3000" },
      data: { name: "Reset Journey", email, password },
    });
    expect(signUp.ok(), await signUp.text()).toBe(true);

    const resetRequest = await page.request.post("/api/auth/request-password-reset", {
      headers: { Origin: "http://localhost:3000" },
      data: { email, redirectTo: "/reset-password" },
    });
    expect(resetRequest.ok(), await resetRequest.text()).toBe(true);

    const token = await waitForResetToken(email);

    // Better Auth puts the token in the emailed link's path; the form reads it from `?token=`.
    await page.goto(`/reset-password?token=${token}`);
    await waitForHydration(page);
    await expect(page.getByRole("heading", { name: "Set a new password" })).toBeVisible();
    await page.locator("#password").fill(newPassword);
    const [resetResponse] = await Promise.all([
      page.waitForResponse(
        response =>
          response.request().method() === "POST" &&
          response.url().endsWith("/api/auth/reset-password")
      ),
      page.getByRole("button", { name: "Save password" }).click(),
    ]);
    expect(resetResponse.ok(), await resetResponse.text()).toBe(true);

    // The sign-up session survives the reset, so /login would bounce a signed-in visitor to the
    // dashboard. Sign out first, or the new password is never actually exercised.
    const signOut = await page.request.post("/api/auth/sign-out", {
      headers: { Origin: "http://localhost:3000" },
    });
    expect(signOut.ok(), await signOut.text()).toBe(true);

    await page.goto("/login");
    await waitForHydration(page);
    await page.locator("#email").fill(email);
    await page.locator("#password").fill(newPassword);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await page.waitForURL("/", { timeout: 10_000 });

    // The new password works: the protected route resolves the fresh session instead of bouncing.
    await page.goto("/dashboard");
    await expect(page.getByRole("heading", { name: /welcome,/i })).toBeVisible();
  });
});

interface MailpitAddress {
  Address: string;
}

interface MailpitMessage {
  ID: string;
  Subject: string;
  To: MailpitAddress[];
}

/** Polls Mailpit until the reset email arrives, then returns the token its link carries. */
async function waitForResetToken(recipient: string): Promise<string> {
  const deadline = Date.now() + 20_000;
  while (Date.now() < deadline) {
    const listResponse = await fetch(`${MAILPIT_URL}/api/v1/messages`);
    const { messages } = (await listResponse.json()) as { messages: MailpitMessage[] };
    const message = messages.find(
      candidate =>
        candidate.Subject === "Reset your password" &&
        candidate.To.some(address => address.Address === recipient)
    );
    if (message) {
      const detailResponse = await fetch(`${MAILPIT_URL}/api/v1/message/${message.ID}`);
      const detail = (await detailResponse.json()) as { Text?: string; HTML?: string };
      const match = /\/api\/auth\/reset-password\/([A-Za-z0-9_-]+)/.exec(
        detail.Text ?? detail.HTML ?? ""
      );
      if (match) return match[1];
    }
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  throw new Error(`No reset email captured for ${recipient} at ${MAILPIT_URL}`);
}
