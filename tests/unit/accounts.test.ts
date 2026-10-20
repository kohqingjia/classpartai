import { describe, expect, it } from "vitest";
import { accountOptions } from "#/features/auth/accounts";

describe("accountOptions", () => {
  it("scopes the query key to the user so cached accounts never leak across accounts", () => {
    expect(accountOptions("user-1").queryKey).toEqual(["auth", "accounts", "user-1"]);
    expect(accountOptions("user-2").queryKey).toEqual(["auth", "accounts", "user-2"]);
  });
});
