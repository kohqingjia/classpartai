import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AssessmentsPage } from "#/features/assessments/components/page";
import { getAssessmentSession } from "#/features/assessments/server-fns";
import { parseImport } from "#/features/assessments/schema";
import fixture from "../fixtures/assessment-fictional.json";

vi.mock("@tanstack/react-router", () => ({
  getRouteApi: () => ({
    useLoaderData: () => ({
      sessions: [
        {
          id: "00000000-0000-4000-8000-000000000001",
          courseId: "00000000-0000-4000-8000-000000000002",
          title: "Fictional session",
          courseTitle: "Fictional course",
          createdAt: new Date(),
        },
      ],
    }),
  }),
  useRouter: () => ({ invalidate: vi.fn<() => Promise<void>>() }),
}));
vi.mock("#/features/assessments/server-fns", () => ({
  getAssessmentSession: vi.fn<() => Promise<unknown>>(),
  importAssessmentSession: vi.fn<() => Promise<unknown>>(),
}));

function renderPage() {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <AssessmentsPage />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.mocked(getAssessmentSession).mockResolvedValue({
    id: "00000000-0000-4000-8000-000000000001",
    courseId: "00000000-0000-4000-8000-000000000002",
    courseTitle: "Fictional course",
    inputs: parseImport({ json: JSON.stringify(fixture) }).inputs,
    createdAt: new Date(),
  });
});

describe("assessment input viewer", () => {
  it("shows fictional inputs, all roster students and verifiable passage references without scoring", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Fictional course — Fictional session" }));
    expect(await screen.findByText(/Fictional Student C.*No observed contribution/)).toBeTruthy();
    expect(screen.getByText(/Fictional development fixture — not real student data/)).toBeTruthy();
    expect(screen.getByText(/fictional-reading-a\/a-p1 · Page 1/)).toBeTruthy();
    expect(screen.getByText(/fictional-reading-b\/b-p2 · Page 2/)).toBeTruthy();
    expect(screen.getByText(/turn-002 ·/)).toBeTruthy();
    expect(screen.getByText(/Reviewed inputs remain read-only/)).toBeTruthy();
  });

  it("surfaces a failed authorised load instead of showing another session", async () => {
    vi.mocked(getAssessmentSession).mockRejectedValueOnce(
      new Error("Assessment session not found")
    );
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Fictional course — Fictional session" }));
    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent",
      "Assessment session not found"
    );
    expect(screen.queryByText(/Fictional Student C/)).toBeNull();
  });
});
