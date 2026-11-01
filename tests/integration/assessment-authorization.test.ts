import {
  getEvidenceRuns,
  getSourcePassage,
  investigateEvidence,
  searchCoursePassages,
} from "#/features/evidence/server-fns";
import { describe, expect, it, vi } from "vitest";
import { auth } from "#/lib/auth.server";
import {
  getAssessmentSession,
  importAssessmentSession,
  listAssessmentSessions,
} from "#/features/assessments/server-fns";
import { refusalFrom } from "./server-fn-harness";

vi.mock("@tanstack/react-start/server", () => ({
  getRequest: () => new Request("http://localhost:3000/_serverFn"),
  setResponseStatus: vi.fn<(code: number) => void>(),
}));
vi.mock("#/lib/auth.server", () => ({
  auth: { api: { getSession: vi.fn<() => Promise<unknown>>() } },
}));
vi.mock("@tanstack/start-storage-context", () => ({
  getStartContext: () => ({ startOptions: {}, contextAfterGlobalMiddlewares: {} }),
}));

describe("assessment endpoint authentication", () => {
  it("refuses anonymous list, detail and import requests before parsing input", async () => {
    vi.mocked(auth.api.getSession).mockResolvedValue(null);
    expect(await refusalFrom(listAssessmentSessions, undefined, "GET")).toEqual({
      status: 401,
      message: "Unauthorized",
    });
    expect(await refusalFrom(getAssessmentSession, { id: "invalid" }, "GET")).toEqual({
      status: 401,
      message: "Unauthorized",
    });
    expect(await refusalFrom(importAssessmentSession, { json: "{" })).toEqual({
      status: 401,
      message: "Unauthorized",
    });
  });
  it("refuses anonymous evidence endpoints before input validation", async () => {
    vi.mocked(auth.api.getSession).mockResolvedValue(null);
    expect(await refusalFrom(getEvidenceRuns, {}, "GET")).toEqual({
      status: 401,
      message: "Unauthorized",
    });
    expect(await refusalFrom(getSourcePassage, {}, "GET")).toEqual({
      status: 401,
      message: "Unauthorized",
    });
    expect(await refusalFrom(searchCoursePassages, {})).toEqual({
      status: 401,
      message: "Unauthorized",
    });
    expect(await refusalFrom(investigateEvidence, {})).toEqual({
      status: 401,
      message: "Unauthorized",
    });
  });
});
