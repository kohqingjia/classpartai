import { describe, expect, it } from "vitest";
import { Route } from "#/routes/api/health";

describe("GET /api/health", () => {
  it("returns status ok and a valid ISO timestamp", async () => {
    const handlers = Route.options.server?.handlers as
      | { GET?: () => Promise<Response> }
      | undefined;
    const getHandler = handlers?.GET;

    if (!getHandler) {
      throw new Error("GET handler is not defined on /api/health");
    }

    const response = await getHandler();
    expect(response.status).toBe(200);

    const json = (await response.json()) as { status: string; timestamp: string };
    expect(json).toMatchObject({
      status: "ok",
    });
    expect(typeof json.timestamp).toBe("string");
    expect(Number.isNaN(Date.parse(json.timestamp))).toBe(false);
  });
});
