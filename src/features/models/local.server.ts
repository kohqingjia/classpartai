import { z } from "zod";
import { env } from "#/env";
import type { Driver, HistoryItem } from "#/features/evidence/agent.server";

export interface ToolDefinition {
  type: string;
  name: string;
  description: string;
  parameters: object;
  strict: boolean;
}
export function tool(name: string, description: string, schema: z.ZodType): ToolDefinition {
  const parameters = z.toJSONSchema(schema);
  delete parameters.$schema;
  return { type: "function", name, description, parameters, strict: true };
}
export function loopbackEndpoint(value: string) {
  const url = new URL(value);
  if (
    url.protocol !== "http:" ||
    !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) ||
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    url.pathname !== "/v1"
  )
    throw new Error("Only a local no-cost model endpoint ending in /v1 is permitted");
  return `${url.origin}/v1/chat/completions`;
}
const Reply = z.object({
  choices: z
    .array(
      z.object({
        message: z.object({
          tool_calls: z
            .array(
              z.object({
                id: z.string().max(200),
                function: z.object({ name: z.string().max(100), arguments: z.string().max(64000) }),
              })
            )
            .max(1),
        }),
      })
    )
    .min(1)
    .max(1),
  usage: z.object({ total_tokens: z.number().int().min(0) }).optional(),
});

export function localDriver(
  instructions: string,
  tools: ToolDefinition[],
  model: string,
  base: string,
  transport: typeof fetch = fetch
): Driver {
  if (/cloud|https?:|\//i.test(model)) throw new Error("Cloud model routing is disabled");
  const endpoint = loopbackEndpoint(base);
  const payload = (history: HistoryItem[]) => {
    const messages: HistoryItem[] = [{ role: "system", content: instructions }];
    for (const item of history) {
      if (item.type === "function_call")
        messages.push({
          role: "assistant",
          content: null,
          tool_calls: [
            {
              id: item.call_id,
              type: "function",
              function: { name: item.name, arguments: item.arguments },
            },
          ],
        });
      else if (item.type === "function_call_output")
        messages.push({ role: "tool", tool_call_id: item.call_id, content: item.output });
      else messages.push(item);
    }
    return {
      model,
      messages,
      tools: tools.map(t => ({
        type: "function",
        function: { name: t.name, description: t.description, parameters: t.parameters },
      })),
      stream: false,
      max_tokens: 4000,
    };
  };
  return {
    estimateTokens: history =>
      new TextEncoder().encode(JSON.stringify(payload(history))).length + 4000,
    async next(history, signal) {
      const response = await transport(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload(history)),
        signal,
        redirect: "error",
      });
      if (!response.ok) {
        await response.body?.cancel();
        throw new Error("Local model unavailable or incompatible");
      }
      const reader = response.body?.getReader();
      if (!reader) throw new Error("Local model response missing");
      let body = "";
      let bytes = 0;
      const decoder = new TextDecoder();
      try {
        while (true) {
          // oxlint-disable-next-line no-await-in-loop -- enforce a streaming byte bound before JSON parsing
          const part = await reader.read();
          if (part.done) break;
          bytes += part.value.length;
          if (bytes > 256000) throw new Error("Local model response too large");
          body += decoder.decode(part.value, { stream: true });
        }
      } finally {
        await reader.cancel();
      }
      const parsed = Reply.safeParse(JSON.parse(body + decoder.decode()));
      if (!parsed.success) throw new Error("Local model must support structured tool calls");
      const estimate = new TextEncoder().encode(JSON.stringify(payload(history)) + body).length;
      return {
        calls: parsed.data.choices[0].message.tool_calls.map(c => ({
          callId: c.id,
          name: c.function.name,
          arguments: c.function.arguments,
        })),
        tokens: parsed.data.usage?.total_tokens ?? estimate,
        usageKind: parsed.data.usage ? "reported" : "estimated",
      };
    },
  };
}
export function configuredDriver(instructions: string, tools: ToolDefinition[]): Driver | null {
  return env.LOCAL_MODEL
    ? localDriver(instructions, tools, env.LOCAL_MODEL, env.LOCAL_MODEL_URL)
    : null;
}
