import { randomBytes, randomUUID } from "node:crypto";
import { test, expect } from "@playwright/test";
import fixture from "../fixtures/assessment-fictional.json" with { type: "json" };
import { fictionalProposal } from "../fixtures/participation-proposal";
import { parseImport } from "../../src/features/assessments/schema";
import { waitForHydration } from "./hydration";

test("requires sign-in for assessment inputs", async ({ page }) => {
  await page.goto("/assessments");
  await expect(page).toHaveURL(/\/login$/);
});

test("imports reviewed inputs and displays a complete roster, rubric and citations", async ({
  page,
}) => {
  // The suite owns an isolated test database. Synthetic content is never imported into a real course.
  const password = `${randomBytes(24).toString("base64url")}9!aA`;
  await page.goto("/signup");
  await waitForHydration(page);
  await page
    .getByLabel("Email", { exact: true })
    .fill(`assessment-${randomUUID()}@example.invalid`);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await page.waitForURL("/dashboard");
  await page.goto("/assessments");
  await waitForHydration(page);
  // Production must reject the explicitly labelled development fixture.
  await page.getByLabel("Reviewed session JSON (maximum 2 MB)").setInputFiles({
    name: "fictional.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(fixture)),
  });
  await page.getByRole("button", { name: "Import inputs", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText(
    "Fictional development fixtures can only be imported in development"
  );
  // Exercise production import using simulated reviewed input, only in the suite's disposable DB.
  const reviewed = { ...fixture, provenance: "reviewed" };
  await page.getByLabel("Reviewed session JSON (maximum 2 MB)").setInputFiles({
    name: "reviewed.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(reviewed)),
  });
  await page.getByRole("button", { name: "Import inputs", exact: true }).click();
  await expect(page.getByRole("region", { name: "Session inputs" })).toBeVisible({
    timeout: 15000,
  });
  await expect(page.getByText(/Fictional Student C.*No observed contribution/)).toBeVisible();
  await expect(page.getByText(/fictional-reading-a\/a-p1 · Page 1/)).toBeVisible();
  await expect(page.getByText(/fictional-reading-b\/b-p2 · Page 2/)).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Fictional participation rubric — version 1" })
  ).toBeVisible();
  await expect(page.getByText(/turn-002 ·/)).toBeVisible();
  await page.reload();
  await waitForHydration(page);
  await page
    .getByRole("button", { name: `${fixture.courseTitle} — ${fixture.sessionTitle}`, exact: true })
    .click();
  await expect(page.getByText(/Fictional Student C.*No observed contribution/)).toBeVisible();
  await page.getByLabel("Search authorised course passages", { exact: true }).fill("observation");
  await page.getByRole("button", { name: "Search passages", exact: true }).click();
  await expect(page.getByRole("button", { name: "Fetch passage a-p1", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Fetch passage a-p1", exact: true }).click();
  await expect(page.getByText(/Retrieved source window/)).toBeVisible();
  await page
    .getByLabel("Participation question for investigation", { exact: true })
    .fill("What course evidence distinguishes observation from interpretation?");
  await page.getByLabel("turn-002", { exact: true }).check();
  await page.getByLabel("Reasoning with evidence", { exact: true }).check();
  await page.getByRole("button", { name: "Investigate evidence", exact: true }).click();
  await expect(
    page.getByText(/Live local-model execution blocked: configure a loopback/)
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "failed · provider_not_configured", exact: true })
  ).toBeVisible();
  await page.reload();
  await waitForHydration(page);
  await page
    .getByRole("button", { name: `${fixture.courseTitle} — ${fixture.sessionTitle}`, exact: true })
    .click();
  await expect(
    page.getByText(/Live local-model execution blocked: configure a loopback/)
  ).toBeVisible();
  // A manual, explicitly unassessed professor draft exercises review and capture without a model.
  await page.getByRole("button", { name: "Run participation workflow", exact: true }).click();
  await page.getByText("Version and execution history", { exact: true }).click();
  await expect(
    page.getByText("configuration_blocked: free_local_model_not_configured", { exact: true })
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Create unassessed professor draft", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Version 1 · Professor draft/edit", exact: true })
  ).toBeVisible();
  await page.getByText("Professor edit — new version", { exact: true }).click();
  await page.getByRole("button", { name: "Load latest draft into editor", exact: true }).click();
  const manual = fictionalProposal(parseImport({ json: JSON.stringify(fixture) }).inputs);
  await page
    .getByLabel("Draft findings and feedback JSON", { exact: true })
    .fill(JSON.stringify(manual));
  await page
    .getByLabel("Reason for this edit", { exact: true })
    .fill("Fictional manual feedback for local capture verification");
  await page.getByRole("button", { name: "Save new professor version", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Version 2 · Professor draft/edit", exact: true })
  ).toBeVisible();
  await page.getByText("Authorised roster test recipients", { exact: true }).click();
  const recipientTag = randomUUID();
  /* oxlint-disable no-await-in-loop -- Each recipient form save refetches and remounts the roster forms; wait for it before editing the next form. */
  for (const student of fixture.roster) {
    await page
      .getByLabel(`${student.displayName} test recipient`, { exact: true })
      .fill(`${recipientTag}-${student.id}@example.invalid`);
    await page.getByRole("button", { name: `Save recipient ${student.id}`, exact: true }).click();
    await expect(
      page.getByRole("button", { name: `Save recipient ${student.id}`, exact: true })
    ).toBeEnabled();
  }
  /* oxlint-enable no-await-in-loop */
  await expect(
    page.getByRole("button", { name: "Send approved feedback to Mailpit", exact: true })
  ).toBeDisabled();
  await page
    .getByLabel("I reviewed this exact version, its evidence, gaps and unresolved issues.", {
      exact: true,
    })
    .check();
  await page
    .getByLabel("Acknowledgement / override reason", { exact: true })
    .fill(
      "I reviewed this fictional manual unassessed draft and its unresolved evidence limitations."
    );
  await page.getByRole("button", { name: "Approve exact version 2", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Send approved feedback to Mailpit", exact: true })
  ).toBeEnabled();
  await page
    .getByRole("button", { name: "Send approved feedback to Mailpit", exact: true })
    .click();
  await Promise.all(
    fixture.roster.map(student =>
      expect(page.getByText(`${student.id}: accepted; attempts: 1`, { exact: true })).toBeVisible()
    )
  );
  await page
    .getByRole("button", { name: "Send approved feedback to Mailpit", exact: true })
    .click();
  const captured = await page.request.get("http://localhost:8025/api/v1/messages");
  expect(captured.ok()).toBe(true);
  const messages = await captured.json();
  const ours = messages.messages.filter((message: { To: Array<{ Address: string }> }) =>
    message.To.some(to => to.Address.includes(recipientTag))
  );
  expect(ours).toHaveLength(3);
  // A new version invalidates sending, including after refresh (actual Bun JSONB runtime).
  await page.getByRole("button", { name: "Load latest draft into editor", exact: true }).click();
  await page
    .getByLabel("Reason for this edit", { exact: true })
    .fill("Review changed, requires fresh exact-version approval");
  await page.getByRole("button", { name: "Save new professor version", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Version 3 · Professor draft/edit", exact: true })
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Send approved feedback to Mailpit", exact: true })
  ).toBeDisabled();
});
