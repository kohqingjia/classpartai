import { z } from "zod";
import { FetchSchema, FinishSchema, SearchSchema } from "./schema";
import type { Driver } from "./agent.server";

function definition(name: string, description: string, schema: z.ZodType) {
  const parameters = z.toJSONSchema(schema);
  delete parameters.$schema;
  return { type: "function", name, description, parameters, strict: true };
}
export const TOOL_DEFINITIONS = [
  definition(
    "search_course_passages",
    "Lexical English full-text search over this session's authorised sources. Query can be reformulated; documentId/version may filter a result's source. No internet.",
    SearchSchema
  ),
  definition(
    "get_source_passage",
    "Fetch a source passage window by returned passageId; offset selects further context. Scope is fixed by the backend.",
    FetchSchema
  ),
  definition(
    "finish_evidence",
    "Finish with sufficient cited evidence or explicit unresolved gaps. Exact quotes and IDs are checked, not factual support. No participation scores.",
    FinishSchema
  ),
];
// Paid provider integration is intentionally inert under the prototype's free-only policy.
export function openAIProvider(
  _apiKey: string,
  _model: string,
  _request: typeof fetch = fetch
): Driver {
  return {
    estimateTokens: () => 0,
    next: async () => {
      throw new Error("Paid model providers are disabled by the free-only policy");
    },
  };
}
