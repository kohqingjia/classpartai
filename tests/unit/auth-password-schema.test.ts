import { describe, expect, it } from "vitest";
import { PasswordSchema } from "#/features/auth/schema/password";

const messages = (password: string) =>
  PasswordSchema.safeParse(password).error?.issues.map(i => i.message) ?? [];

describe("PasswordSchema", () => {
  it("accepts a password with a number and a symbol", () => {
    expect(PasswordSchema.safeParse("correct-horse1!").success).toBe(true);
  });

  it("rejects a password with no number", () => {
    expect(messages("no-digits-here!")).toContain("Password must contain at least one number");
  });

  it("rejects a password with no symbol", () => {
    expect(messages("nosymbols123")).toContain("Password must contain at least one symbol");
  });

  it("rejects a password shorter than 8 characters", () => {
    expect(messages("a1!")).toContain("Password must be at least 8 characters");
  });

  it("rejects a password longer than 128 characters", () => {
    expect(messages(`${"a1!".repeat(50)}x`)).toContain("Password must be at most 128 characters");
  });

  it("counts any non-alphanumeric character as a symbol", () => {
    for (const password of ["spaced out 1", "emoji-pass1🎉", "under_score1"]) {
      expect(PasswordSchema.safeParse(password).success).toBe(true);
    }
  });
});
