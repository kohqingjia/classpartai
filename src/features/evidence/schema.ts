import { z } from "zod";
import { ValidationError } from "#/features/auth/session";

const key = z.string().min(1).max(80);
export const SearchSchema = z
  .object({
    query: z.string().trim().min(1).max(240),
    documentId: key.nullable(),
    version: key.nullable(),
    limit: z.number().int().min(1).max(5),
  })
  .strict();
export const FetchSchema = z
  .object({ passageId: z.uuid(), offset: z.number().int().min(0).max(19999) })
  .strict();
export const FinishSchema = z
  .object({
    status: z.enum(["sufficient", "gap"]),
    explanation: z.string().trim().min(1).max(2000),
    turnIds: z.array(key).max(8),
    citations: z
      .array(
        z
          .object({
            passageId: z.uuid(),
            excerpt: z.string().trim().min(1).max(2000),
            relevance: z.string().trim().min(1).max(800),
            relationship: z.enum(["supports", "conflicts", "context"]),
          })
          .strict()
      )
      .max(12),
    conflicts: z.array(z.string().min(1).max(800)).max(8),
    gaps: z.array(z.string().min(1).max(800)).max(8),
  })
  .strict()
  .superRefine((value, ctx) => {
    if (value.status === "sufficient" && (!value.citations.length || value.gaps.length))
      ctx.addIssue({
        code: "custom",
        message: "Sufficient evidence needs citations and no unresolved gaps",
      });
    if (value.conflicts.length && !value.citations.some(c => c.relationship === "conflicts")) {
      ctx.addIssue({
        code: "custom",
        message: "Conflicting evidence needs a cited conflicting passage",
      });
    }
    if (value.status === "gap" && !value.gaps.length)
      ctx.addIssue({
        code: "custom",
        message: "A gap completion must identify what remains unknown",
      });
  });
export const InvestigationSchema = z
  .object({
    sessionId: z.uuid(),
    question: z.string().trim().min(5).max(1500),
    turnIds: z.array(key).min(1).max(8),
    criterionIds: z.array(key).min(1).max(6),
  })
  .strict();
export type Investigation = z.infer<typeof InvestigationSchema>;
export type Completion = z.infer<typeof FinishSchema>;

export function parseInvestigation(value: unknown) {
  const parsed = InvestigationSchema.safeParse(value);
  if (!parsed.success) throw new ValidationError(parsed.error.issues[0].message);
  return parsed.data;
}
export function parseEvidenceScope(value: unknown) {
  const parsed = z.object({ sessionId: z.uuid() }).strict().safeParse(value);
  if (!parsed.success) throw new ValidationError(parsed.error.issues[0].message);
  return parsed.data;
}
export function parseSearchRequest(value: unknown) {
  const parsed = z.object({ sessionId: z.uuid(), search: SearchSchema }).strict().safeParse(value);
  if (!parsed.success) throw new ValidationError(parsed.error.issues[0].message);
  return parsed.data;
}
export function parsePassageRequest(value: unknown) {
  const parsed = z.object({ sessionId: z.uuid(), passage: FetchSchema }).strict().safeParse(value);
  if (!parsed.success) throw new ValidationError(parsed.error.issues[0].message);
  return parsed.data;
}

export interface Passage {
  passageId: string;
  documentId: string;
  version: string;
  title: string;
  source: string;
  passageKey: string;
  page: number;
  text: string;
  offset: number;
  truncated: boolean;
}
export interface EvidenceBundle {
  contractVersion: 1;
  sessionId: string;
  question: string;
  transcriptVersion: string;
  rubric: { id: string; version: string; criterionIds: string[] };
  status: "sufficient" | "gap";
  explanation: string;
  turnIds: string[];
  citations: Array<
    Omit<Passage, "text" | "offset" | "truncated"> & {
      excerpt: string;
      relevance: string;
      relationship: "supports" | "conflicts" | "context";
    }
  >;
  conflicts: string[];
  gaps: string[];
  citationValidity: "authorised_retrieved_exact_excerpt";
  supportValidation: "model_proposed_professor_review_required";
}
export interface Action {
  id: string;
  tool: string;
  arguments: string;
  outcome: "started" | "ok" | "invalid";
  resultReferences: string[];
  summary: string;
}
export interface Progress {
  modelCalls: number;
  toolCalls: number;
  tokens: number;
  returnedCharacters: number;
  actions: Action[];
  bundle: EvidenceBundle | null;
}

export interface SourceManifest {
  sessionId: string;
  formatVersion: number;
  transcriptVersion: string;
  rubric: { id: string; version: string };
  sources: Array<{ documentId: string; version: string; digest: string }>;
  budgets: Record<string, number>;
}
