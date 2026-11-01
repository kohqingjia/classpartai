import { describe, expect, it, vi } from "vitest";
import { openAIProvider, TOOL_DEFINITIONS } from "#/features/evidence/provider.server";
import { localDriver, loopbackEndpoint } from "#/features/models/local.server";
import { INSTRUCTIONS } from "#/features/evidence/agent.server";

describe("free-only model transport with explicit HTTP doubles", () => {
  it("never calls a paid provider even when a key is supplied", async () => {
    const transport = vi.fn<typeof fetch>();
    await expect(
      openAIProvider("fictional-test-key", "test", transport).next([], new AbortController().signal)
    ).rejects.toThrow("Paid model providers are disabled");
    expect(transport).not.toHaveBeenCalled();
  });
  it("permits only loopback endpoints without credentials or redirects", () => {
    expect(loopbackEndpoint("http://127.0.0.1:11434/v1")).toContain("127.0.0.1");
    expect(() => loopbackEndpoint("https://api.openai.com/v1")).toThrow("Only a local");
    expect(() => loopbackEndpoint("http://user:password@localhost/v1")).toThrow("Only a local");
  });
  it("sends allowlisted tools and replays tool results without hidden reasoning", async () => {
    const transport = vi.fn<typeof fetch>().mockResolvedValue(
      Response.json({
        choices: [
          {
            message: {
              tool_calls: [
                { id: "test-call", function: { name: "finish_evidence", arguments: "{}" } },
              ],
            },
          },
        ],
        usage: { total_tokens: 42 },
      })
    );
    const driver = localDriver(
      INSTRUCTIONS,
      TOOL_DEFINITIONS,
      "test-double",
      "http://localhost:11434/v1",
      transport
    );
    const result = await driver.next(
      [
        { role: "user", content: "Fictional data" },
        {
          type: "function_call",
          name: "search_course_passages",
          arguments: "{}",
          call_id: "prior",
        },
        { type: "function_call_output", call_id: "prior", output: "[]" },
      ],
      new AbortController().signal
    );
    expect(result.tokens).toBe(42);
    expect(result.usageKind).toBe("reported");
    expect(result.calls).toHaveLength(1);
    const body = transport.mock.calls[0][1]?.body;
    if (typeof body !== "string") throw new Error("Expected JSON body");
    expect(JSON.parse(body).messages[0].content).toContain("UNTRUSTED DATA");
    expect(JSON.parse(body).tools).toHaveLength(3);
    expect(driver.estimateTokens([])).toBeGreaterThan(4000);
  });
  it("labels estimates, rejects malformed/oversized replies and sanitises provider errors", async () => {
    const transport = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json({ choices: [{ message: { tool_calls: [] } }] }))
      .mockResolvedValueOnce(new Response("x".repeat(256001)))
      .mockResolvedValueOnce(Response.json({}))
      .mockResolvedValueOnce(new Response("private remote details", { status: 500 }));
    const driver = localDriver(
      INSTRUCTIONS,
      TOOL_DEFINITIONS,
      "test",
      "http://localhost:11434/v1",
      transport
    );
    expect((await driver.next([], new AbortController().signal)).usageKind).toBe("estimated");
    await expect(driver.next([], new AbortController().signal)).rejects.toThrow("too large");
    await expect(driver.next([], new AbortController().signal)).rejects.toThrow(
      "structured tool calls"
    );
    await expect(driver.next([], new AbortController().signal)).rejects.toThrow(
      "Local model unavailable"
    );
  });
});
