import { describe, expect, it } from "vitest";
import { CreateNoteInput, DeleteNoteInput } from "#/features/notes/schema";

describe("Notes Input Validators", () => {
  describe("CreateNoteInput", () => {
    it("validates valid input", () => {
      expect(CreateNoteInput.parse({ title: "Valid" })).toEqual({ title: "Valid" });
    });

    it("rejects non-string title", () => {
      expect(() => CreateNoteInput.parse({ title: 123 })).toThrow(/invalid/i);
    });

    it("rejects empty title", () => {
      expect(() => CreateNoteInput.parse({ title: "   " })).toThrow(/title is required/i);
    });

    it("rejects title exceeding 255 characters", () => {
      expect(() => CreateNoteInput.parse({ title: "a".repeat(256) })).toThrow(
        /must be 255 characters or fewer/i
      );
    });
  });

  describe("DeleteNoteInput", () => {
    it("validates valid input", () => {
      expect(DeleteNoteInput.parse({ id: 5 })).toEqual({ id: 5 });
    });

    it("rejects invalid id", () => {
      expect(() => DeleteNoteInput.parse({ id: "invalid" })).toThrow(/invalid/i);
    });
  });
});
