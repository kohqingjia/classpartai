import { describe, expect, it } from "vitest";
import { getSessionUser } from "#/features/auth/session";

describe("getSessionUser helper", () => {
  it("returns null when session is null or has no user", () => {
    expect(getSessionUser(null)).toBeNull();
    expect(getSessionUser({})).toBeNull();
  });

  it("returns sanitized SessionUser when valid session exists", () => {
    const rawSession = {
      user: {
        id: "usr_42",
        email: "alice@example.com",
        name: "Alice",
        image: "https://example.com/avatar.jpg",
        createdAt: new Date(),
        updatedAt: new Date(),
        emailVerified: true,
      },
      session: {
        id: "sess_42",
        userId: "usr_42",
        expiresAt: new Date(),
        token: "valid_token",
        createdAt: new Date(),
        updatedAt: new Date(),
      },
    };

    const user = getSessionUser(rawSession);
    expect(user).toEqual({
      id: "usr_42",
      email: "alice@example.com",
      name: "Alice",
      image: "https://example.com/avatar.jpg",
    });
  });
});
