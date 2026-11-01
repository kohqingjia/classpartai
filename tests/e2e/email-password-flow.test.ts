import { randomBytes, randomUUID } from "node:crypto";
import { test, expect } from "@playwright/test";
import { waitForHydration } from "./hydration";

test("registers without verification, signs out, and opens the workspace after password login", async ({
  page,
}) => {
  const email = `e2e-password-${randomUUID()}@example.com`;
  const password = `${randomBytes(24).toString("base64url")}9!aA`;
  const browserErrors: string[] = [];
  page.on("pageerror", error => browserErrors.push(error.message));

  await page.goto("/signup");
  await waitForHydration(page);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  const [signup] = await Promise.all([
    page.waitForResponse(response => response.url().endsWith("/api/auth/sign-up/email")),
    page.getByRole("button", { name: "Create account", exact: true }).click(),
  ]);
  expect(signup.status()).toBe(200);
  await page.waitForURL("/dashboard");
  await expect(page.getByRole("heading", { name: `Welcome, ${email}`, exact: true })).toBeVisible();
  const signupSession = await page.request.get("/api/auth/get-session");
  expect((await signupSession.json()).user.emailVerified).toBe(false);

  const [signout] = await Promise.all([
    page.waitForResponse(response => response.url().endsWith("/api/auth/sign-out")),
    page.getByRole("button", { name: "Sign out", exact: true }).click(),
  ]);
  expect(signout.status()).toBe(200);
  await expect(page.getByRole("button", { name: "Sign out", exact: true })).toBeHidden();
  const signedOutSession = await page.request.get("/api/auth/get-session");
  expect(await signedOutSession.json()).toBeNull();

  await page.goto("/login");
  await waitForHydration(page);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  const [login] = await Promise.all([
    page.waitForResponse(response => response.url().endsWith("/api/auth/sign-in/email")),
    page.getByRole("button", { name: "Sign in", exact: true }).click(),
  ]);
  expect(login.status()).toBe(200);
  await page.waitForURL("/");
  await page.getByRole("link", { name: "Open workspace", exact: true }).click();
  await page.waitForURL("/dashboard");
  await expect(page.getByRole("heading", { name: `Welcome, ${email}`, exact: true })).toBeVisible();
  expect(browserErrors).toEqual([]);
});
