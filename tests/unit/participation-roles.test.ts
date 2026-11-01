import { describe, it, expect } from "vitest";
import { z } from "zod";
import { SharedBudget, WORKFLOW_LIMITS } from "#/features/models/budget";
import { feedbackFor, judge, modelAudit, roleResult } from "#/features/participation/roles.server";
import type { DriverFactory } from "#/features/participation/roles.server";
import type { WorkflowProgress } from "#/features/participation/schema";
import { parseImport } from "#/features/assessments/schema";
import { composeDraft } from "#/features/participation/validation";
import { fictionalProposal } from "../fixtures/participation-proposal";
import fixture from "../fixtures/assessment-fictional.json";

const inputs = parseImport({ json: JSON.stringify(fixture) }).inputs;
const wrong: DriverFactory = () => ({
  estimateTokens: () => 1,
  next: async () => ({
    tokens: 1,
    calls: [{ callId: "wrong", name: "send_email", arguments: "{}" }],
  }),
});

function budget() {
  const progress: WorkflowProgress = {
    modelCalls: 0,
    toolCalls: 0,
    tokens: 0,
    usageKind: "reported",
    actions: [],
    latestDraftId: null,
    evidenceRunIds: [],
  };
  return new SharedBudget(progress, new AbortController().signal, async () => undefined);
}
// These providers are explicit deterministic role-protocol test doubles, never live evaluations.
describe("local role contracts and shared bounded execution", () => {
  it("lets a role correct malformed arguments with tool feedback, bounded to two attempts", async () => {
    let count = 0;
    const histories: string[] = [];
    const factory: DriverFactory = () => ({
      estimateTokens: () => 1,
      next: async history => {
        count++;
        histories.push(JSON.stringify(history));
        return {
          tokens: 5,
          usageKind: "estimated",
          calls: [
            {
              callId: `call-${count}`,
              name: "finish",
              arguments: count === 1 ? "{" : '{"answer":"checked"}',
            },
          ],
        };
      },
    });
    const guard = budget();
    expect(
      await roleResult(
        "finish",
        z.object({ answer: z.string() }),
        "Return result",
        { input: "untrusted" },
        guard,
        factory
      )
    ).toEqual({ answer: "checked" });
    expect(histories[1]).toContain("Malformed role result");
    expect(guard.progress).toMatchObject({
      modelCalls: 2,
      toolCalls: 2,
      tokens: 10,
      usageKind: "includes_estimates",
    });
    await expect(
      roleResult("finish", z.object({ answer: z.number() }), "Return result", {}, budget(), factory)
    ).rejects.toThrow("valid structured");
  });
  it("blocks unavailable configuration and refuses unsupported role actions", async () => {
    await expect(
      roleResult("finish", z.object({}), "Return result", {}, budget(), () => null)
    ).rejects.toThrow("configuration blocked");
    await expect(
      roleResult("finish", z.object({}), "Return result", {}, budget(), wrong)
    ).rejects.toThrow("unsupported tool");
  });
  it("passes exact reviewed versions to the judge and only target-student information to feedback", async () => {
    const proposal = fictionalProposal(inputs);
    const requests: Array<{ name: string; instructions: string; content: string }> = [];
    const factory: DriverFactory = (instructions, tools) => ({
      estimateTokens: () => 1,
      next: async history => {
        requests.push({ name: tools[0].name, instructions, content: String(history[0].content) });
        const name = tools[0].name;
        let result: unknown;
        if (name === "finish_rubric_judgement") {
          result = { findings: proposal.findings };
        } else if (name === "finish_assessment_audit") {
          result = {
            issues: [],
            resolvedIssueIds: [],
            resolutionReason: "Not applicable",
            notes: "Fictional audit",
          };
        } else {
          result = {
            status: "needs_evidence",
            question: "What resource helps frame a future contribution?",
          };
        }
        return {
          tokens: 2,
          calls: [{ callId: "double", name, arguments: JSON.stringify(result) }],
        };
      },
    });
    const guard = budget();
    const judged = await judge(inputs, [], guard, factory);
    const draft = composeDraft(judged, inputs, "Test double only");
    expect(await modelAudit(inputs, draft, [], guard, factory)).toMatchObject({ issues: [] });
    expect(await feedbackFor("student-c", inputs, proposal, [], guard, factory)).toMatchObject({
      status: "needs_evidence",
    });
    await expect(feedbackFor("invented", inputs, proposal, [], guard, factory)).rejects.toThrow(
      "Unknown feedback student"
    );
    expect(requests.map(r => r.name)).toEqual([
      "finish_rubric_judgement",
      "finish_assessment_audit",
      "finish_student_feedback",
    ]);
    expect(requests.every(r => r.instructions.includes("UNTRUSTED DATA"))).toBe(true);
    const judgeData = JSON.parse(requests[0].content).untrustedData;
    expect(judgeData.transcript.version).toBe(inputs.transcript.version);
    expect(judgeData.rubric.version).toBe(inputs.rubric.version);
    const feedbackData = JSON.parse(requests[2].content).untrustedData;
    expect(feedbackData.student.id).toBe("student-c");
    expect(
      feedbackData.findings.every((f: { studentId: string }) => f.studentId === "student-c")
    ).toBe(true);
    expect(feedbackData.turns).toEqual([]);
    expect(feedbackData).not.toHaveProperty("roster");
    expect(guard.progress.modelCalls).toBe(3);
  });
  it("enforces shared token/history/deadline limits and rejects invalid provider accounting", async () => {
    const guard = budget();
    const driver = {
      estimateTokens: () => 1,
      next: async () => ({ tokens: WORKFLOW_LIMITS.tokens + 1, calls: [] }),
    };
    await expect(guard.wrap(driver).next([], guard.signal)).rejects.toThrow(
      "Shared workflow budget"
    );
    await expect(
      budget().call({ ...driver, next: async () => ({ tokens: -1, calls: [] }) }, [], guard.signal)
    ).rejects.toThrow("Invalid provider usage");
    const small = budget();
    await expect(
      small.call(
        driver,
        [{ role: "user", content: "x".repeat(WORKFLOW_LIMITS.historyBytes) }],
        small.signal
      )
    ).rejects.toThrow("Shared workflow budget");
    const aborted = new SharedBudget(budget().progress, AbortSignal.abort(), async () => undefined);
    expect(() => aborted.tool()).toThrow("Shared workflow budget");
  });
});
