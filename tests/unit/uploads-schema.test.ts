import { describe, expect, it } from "vitest";
import { parseUploadRequest } from "#/features/uploads/schema";

describe("parseUploadRequest", () => {
  it("returns the parsed request", () => {
    const input = { filename: "notes.txt", contentType: "text/plain", size: 12 };
    expect(parseUploadRequest(input)).toEqual(input);
  });

  it("throws the first issue's message for a malformed body", () => {
    expect(() => parseUploadRequest({})).toThrow(
      "Invalid input: expected string, received undefined"
    );
  });
});
