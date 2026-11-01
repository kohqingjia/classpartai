import { describe, expect, it } from "vitest";
import { ValidationError } from "#/features/auth/session";
import fixture from "../fixtures/assessment-fictional.json";
import { parseImport, parseSessionId } from "#/features/assessments/schema";

function parse(value: unknown) {
  return parseImport({ json: JSON.stringify(value) });
}

describe("assessment input validation", () => {
  it("keeps the complete roster, including a student with no observed turns", () => {
    const { inputs } = parse(fixture);
    expect(inputs.roster).toHaveLength(3);
    const speakers = inputs.transcript.turns.flatMap(t =>
      t.speaker.kind === "student" ? [t.speaker.studentId] : []
    );
    expect(speakers).not.toContain(inputs.roster[2].id);
    expect(inputs.documents.map(d => d.passages[0].page)).toEqual([1, 2]);
  });

  it("rejects unreviewed transcripts", () => {
    expect(() =>
      parse({ ...fixture, transcript: { ...fixture.transcript, reviewStatus: "draft" } })
    ).toThrow(ValidationError);
  });

  it("rejects attribution outside the roster", () => {
    const value = structuredClone(fixture);
    value.transcript.turns[1].speaker.studentId = "missing";
    expect(() => parse(value)).toThrow("Student attribution must reference the session roster");
  });

  it("rejects duplicate stable turn and roster identifiers", () => {
    const value = structuredClone(fixture);
    value.transcript.turns[1].id = value.transcript.turns[0].id;
    expect(() => parse(value)).toThrow("Duplicate turn identifiers");
    expect(() => parse({ ...fixture, roster: [...fixture.roster, fixture.roster[0]] })).toThrow(
      "Duplicate roster identifiers"
    );
  });

  it("rejects inverted and unordered timestamps", () => {
    const value = structuredClone(fixture);
    value.transcript.turns[1].endMs = 1;
    expect(() => parse(value)).toThrow("Turn timestamps");
    value.transcript.turns[1].endMs = 12000;
    value.transcript.turns[2].startMs = 0;
    expect(() => parse(value)).toThrow("Turn timestamps");
  });

  it("rejects inverted score ranges and missing rubric versions", () => {
    const value = structuredClone(fixture);
    value.rubric.criteria[0].maxScore = 0;
    expect(() => parse(value)).toThrow("score range");
    expect(() => parse({ ...fixture, rubric: { ...fixture.rubric, version: "" } })).toThrow(
      ValidationError
    );
  });

  it("requires course document authorisation and valid page references", () => {
    const value = structuredClone(fixture);
    value.documents[0].authorisedForCourse = false;
    expect(() => parse(value)).toThrow(ValidationError);
    value.documents[0].authorisedForCourse = true;
    value.documents[0].passages[0].page = 0;
    expect(() => parse(value)).toThrow(ValidationError);
  });

  it("returns a plain validation error for malformed or oversized JSON", () => {
    expect(() => parseImport({ json: "{" })).toThrow("Choose a valid JSON input file");
    expect(() => parseImport({ json: "a".repeat(2 * 1024 * 1024 + 1) })).toThrow(ValidationError);
    expect(() => parseSessionId({ id: "not-an-id" })).toThrow(ValidationError);
  });
});
