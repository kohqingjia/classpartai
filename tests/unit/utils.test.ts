import { describe, expect, test } from "vitest";

import { cn, maskEmail } from "#/lib/utils";

describe("cn", () => {
  test("merges conditional classes and resolves Tailwind conflicts", () => {
    const shouldHide = false;

    expect(cn("px-2", shouldHide && "hidden", "px-4", ["text-sm", "text-lg"])).toBe("px-4 text-lg");
  });
});

describe("maskEmail", () => {
  test("keeps the domain and one local character", () => {
    expect(maskEmail("alice@example.com")).toBe("a***@example.com");
  });
});
