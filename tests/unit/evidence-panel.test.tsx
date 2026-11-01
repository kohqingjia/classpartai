import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { EvidencePanel } from "#/features/evidence/components/panel";
import {
  getEvidenceRuns,
  getSourcePassage,
  investigateEvidence,
  searchCoursePassages,
} from "#/features/evidence/server-fns";
import { emptyProgress, validateCompletion } from "#/features/evidence/agent.server";
import { parseImport } from "#/features/assessments/schema";
import fixture from "../fixtures/assessment-fictional.json";

vi.mock("#/features/evidence/server-fns", () => ({
  getEvidenceRuns: vi.fn<() => Promise<unknown>>(),
  getSourcePassage: vi.fn<() => Promise<unknown>>(),
  investigateEvidence: vi.fn<() => Promise<unknown>>(),
  searchCoursePassages: vi.fn<() => Promise<unknown>>(),
}));
const sessionId = "00000000-0000-4000-8000-000000000001";
const inputs = parseImport({ json: JSON.stringify(fixture) }).inputs;
const passage = {
  passageId: "00000000-0000-4000-8000-000000000002",
  documentId: "fictional-reading-a",
  version: "1",
  title: "Fictional handout",
  source: "Fictional source",
  passageKey: "a-p1",
  page: 1,
  text: "An observation describes an event.",
  offset: 0,
  truncated: false,
};
function renderPanel() {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <EvidencePanel sessionId={sessionId} inputs={inputs} />
    </QueryClientProvider>
  );
}
beforeEach(() => {
  vi.mocked(getEvidenceRuns).mockResolvedValue([]);
  vi.mocked(searchCoursePassages).mockResolvedValue([]);
  vi.mocked(getSourcePassage).mockResolvedValue(passage);
  vi.mocked(investigateEvidence).mockResolvedValue({ id: sessionId });
});

describe("evidence panel with explicit backend test doubles", () => {
  it("keeps empty lexical search separate from absence of evidence and fetches source text", async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.type(screen.getByLabelText("Search authorised course passages"), "observation");
    await user.click(screen.getByRole("button", { name: "Search passages" }));
    expect(await screen.findByText(/No lexical matches/)).toBeTruthy();
    vi.mocked(searchCoursePassages).mockResolvedValueOnce([{ ...passage, rankPosition: 1 }]);
    await user.click(screen.getByRole("button", { name: "Search passages" }));
    await user.click(await screen.findByRole("button", { name: "Fetch passage a-p1" }));
    expect(await screen.findByText(/Retrieved source window/)).toBeTruthy();
  });

  it("displays persisted actions and a review-labelled evidence bundle, not a score", async () => {
    const request = {
      sessionId,
      question: "Fictional evidence question",
      turnIds: ["turn-002"],
      criterionIds: ["reasoning"],
    };
    const progress = emptyProgress();
    progress.bundle = validateCompletion(
      {
        status: "sufficient",
        explanation: "Fictional test completion",
        turnIds: ["turn-002"],
        citations: [
          {
            passageId: passage.passageId,
            excerpt: passage.text,
            relevance: "Defines the fictional concept",
            relationship: "supports",
          },
        ],
        conflicts: [],
        gaps: [],
      },
      [passage],
      request,
      inputs
    );
    progress.actions = [
      {
        id: "test-call",
        tool: "get_source_passage",
        arguments: JSON.stringify({ passageId: passage.passageId, offset: 0 }),
        outcome: "ok",
        resultReferences: [passage.passageId],
        summary: "Fictional tool result",
      },
    ];
    vi.mocked(getEvidenceRuns).mockResolvedValue([
      {
        id: sessionId,
        sessionId,
        request,
        manifest: {
          sessionId,
          formatVersion: 1,
          transcriptVersion: "review-1",
          rubric: { id: "test", version: "1" },
          sources: [],
          budgets: {},
        },
        model: "explicit-test-double",
        promptVersion: "test",
        status: "completed",
        progress,
        stopReason: "model_finished_sufficient",
        createdAt: new Date(),
        deadlineAt: new Date(),
        updatedAt: new Date(),
      },
    ]);
    const user = userEvent.setup();
    renderPanel();
    expect(await screen.findByRole("region", { name: "Evidence bundle" })).toBeTruthy();
    expect(screen.getByText(/factual support and relevance are model proposals/)).toBeTruthy();
    expect(screen.getByText(/get_source_passage \(ok\)/)).toBeTruthy();
    await user.type(
      screen.getByLabelText("Participation question for investigation"),
      "Fictional new question"
    );
    await user.click(screen.getByLabelText("turn-002"));
    await user.click(screen.getByLabelText("Reasoning with evidence"));
    await user.click(screen.getByRole("button", { name: "Investigate evidence" }));
    await waitFor(() =>
      expect(investigateEvidence).toHaveBeenCalledWith({
        data: {
          sessionId,
          question: "Fictional new question",
          turnIds: ["turn-002"],
          criterionIds: ["reasoning"],
        },
      })
    );
  });

  it("surfaces backend failures without replacing them with fake evidence", async () => {
    vi.mocked(searchCoursePassages).mockRejectedValueOnce(new Error("Source passage not found"));
    const user = userEvent.setup();
    renderPanel();
    await user.type(screen.getByLabelText("Search authorised course passages"), "observation");
    await user.click(screen.getByRole("button", { name: "Search passages" }));
    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent",
      "Source passage not found"
    );
  });
});
