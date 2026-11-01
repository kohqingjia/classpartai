import { z } from "zod";
import { ValidationError } from "#/features/auth/session";

const id = z.string().min(1).max(80);
export const CitationSchema = z.object({ evidenceRunId: z.uuid(), passageId: z.uuid() }).strict();
export const FindingSchema = z
  .object({
    studentId: id,
    criterionId: id,
    status: z.enum(["scored", "insufficient_evidence"]),
    score: z.number().finite().nullable(),
    turnIds: z.array(id).max(30),
    citations: z.array(CitationSchema).max(12),
    justification: z.string().trim().min(1).max(1500),
    limitations: z.array(z.string().min(1).max(500)).max(10),
  })
  .strict();
export const FeedbackSchema = z
  .object({
    studentId: id,
    strengths: z.string().trim().min(1).max(1500),
    nextStep: z.string().trim().min(1).max(1500),
    limitations: z.array(z.string().min(1).max(500)).max(10),
    turnIds: z.array(id).max(30),
    citations: z.array(CitationSchema).max(12),
    goalIds: z.array(id).max(10),
  })
  .strict();
export const ProposalSchema = z
  .object({
    findings: z.array(FindingSchema).max(15000),
    feedback: z.array(FeedbackSchema).max(500),
  })
  .strict();
export const ModelAuditSchema = z
  .object({
    issues: z
      .array(
        z
          .object({
            id,
            studentId: id.nullable(),
            criterionId: id.nullable(),
            detail: z.string().min(1).max(1000),
            kind: z.enum(["support", "attribution", "contradiction", "feedback", "uncertainty"]),
          })
          .strict()
      )
      .max(100),
    resolvedIssueIds: z.array(id).max(100),
    resolutionReason: z.string().min(1).max(1000),
    notes: z.string().min(1).max(1500),
  })
  .strict();
export type Finding = z.infer<typeof FindingSchema>;
export type Feedback = z.infer<typeof FeedbackSchema>;
export type Proposal = z.infer<typeof ProposalSchema>;
export type ModelAudit = z.infer<typeof ModelAuditSchema>;
export interface AuditIssue {
  id: string;
  studentId: string | null;
  criterionId: string | null;
  kind: string;
  detail: string;
  severity: "blocking" | "review";
  disposition: "open" | "revised";
  resolution: string | null;
}
export interface DraftContent extends Proposal {
  audit: { modelReviewed: boolean; notes: string; issues: AuditIssue[] };
  revisionNote: string;
}
export interface WorkflowProgress {
  modelCalls: number;
  toolCalls: number;
  tokens: number;
  usageKind: "reported" | "includes_estimates";
  actions: Array<{
    id: string;
    tool: string;
    arguments: string;
    summary: string;
    outcome: "started" | "ok" | "invalid";
  }>;
  latestDraftId: string | null;
  evidenceRunIds: string[];
}

export function parseParticipationScope(value: unknown) {
  const parsed = z.object({ sessionId: z.uuid() }).strict().safeParse(value);
  if (!parsed.success) throw new ValidationError(parsed.error.issues[0].message);
  return parsed.data;
}
export function parseDraftEdit(value: unknown) {
  const parsed = z
    .object({
      sessionId: z.uuid(),
      expectedVersion: z.number().int().min(1),
      proposal: ProposalSchema,
      note: z.string().trim().min(3).max(1000),
    })
    .strict()
    .safeParse(value);
  if (!parsed.success) throw new ValidationError(parsed.error.issues[0].message);
  return parsed.data;
}
export function parseRecipient(value: unknown) {
  const parsed = z
    .object({ sessionId: z.uuid(), studentId: id, email: z.email().max(200) })
    .strict()
    .safeParse(value);
  if (!parsed.success) throw new ValidationError(parsed.error.issues[0].message);
  return parsed.data;
}
export function parseApproval(value: unknown) {
  const parsed = z
    .object({
      sessionId: z.uuid(),
      draftId: z.uuid(),
      acknowledge: z.boolean(),
      reason: z.string().trim().max(1500),
    })
    .strict()
    .safeParse(value);
  if (!parsed.success) throw new ValidationError(parsed.error.issues[0].message);
  return parsed.data;
}
export function parseDelivery(value: unknown) {
  const parsed = z.object({ sessionId: z.uuid(), approvalId: z.uuid() }).strict().safeParse(value);
  if (!parsed.success) throw new ValidationError(parsed.error.issues[0].message);
  return parsed.data;
}
