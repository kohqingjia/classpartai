import { z } from "zod";
import { ValidationError } from "#/features/auth/session";

const id = z
  .string()
  .regex(
    /^[A-Za-z0-9_-]{1,80}$/,
    "Use a stable identifier of 1–80 letters, numbers, underscores or hyphens"
  );
const label = z.string().trim().min(1).max(200);
const text = z.string().trim().min(1).max(20000);

export const AssessmentInputsSchema = z
  .object({
    formatVersion: z.literal(1),
    provenance: z.enum(["reviewed", "fictional-development"]),
    courseTitle: label,
    sessionTitle: label,
    learningGoals: z
      .array(z.object({ id, text, approved: z.literal(true) }))
      .max(20)
      .optional(),
    roster: z
      .array(z.object({ id, displayName: label }))
      .min(1)
      .max(500),
    transcript: z.object({
      version: id,
      reviewStatus: z.literal("reviewed"),
      turns: z
        .array(
          z.object({
            id,
            startMs: z.number().int().min(0),
            endMs: z.number().int().min(0),
            speaker: z.discriminatedUnion("kind", [
              z.object({ kind: z.literal("professor"), label }),
              z.object({ kind: z.literal("student"), studentId: id }),
              z.object({
                kind: z.literal("uncertain"),
                label,
                candidateStudentIds: z.array(id).max(10),
                reason: text,
              }),
            ]),
            text,
          })
        )
        .min(1)
        .max(5000),
    }),
    rubric: z.object({
      id,
      version: id,
      title: label,
      aggregation: z.object({ method: z.literal("sum") }).optional(),
      criteria: z
        .array(
          z.object({
            id,
            title: label,
            description: text,
            kind: z.enum(["qualitative", "observable-participation"]).optional(),
            noContributionScore: z.number().finite().optional(),
            requiresCourseEvidence: z.boolean().optional(),
            minScore: z.number().int().min(0).max(100),
            maxScore: z.number().int().min(0).max(100),
          })
        )
        .min(1)
        .max(30),
    }),
    documents: z
      .array(
        z.object({
          id,
          version: id,
          title: label,
          source: label,
          authorisedForCourse: z.literal(true),
          passages: z
            .array(z.object({ id, page: z.number().int().min(1), text }))
            .min(1)
            .max(1000),
        })
      )
      .min(1)
      .max(100),
  })
  .superRefine((data, ctx) => {
    function unique(ids: string[], name: string) {
      if (new Set(ids).size !== ids.length)
        ctx.addIssue({ code: "custom", message: `Duplicate ${name} identifiers` });
    }
    unique(
      data.roster.map(s => s.id),
      "roster"
    );
    unique(
      data.transcript.turns.map(t => t.id),
      "turn"
    );
    unique(
      data.rubric.criteria.map(c => c.id),
      "criterion"
    );
    unique(
      data.documents.map(d => d.id),
      "document"
    );
    const students = new Set(data.roster.map(s => s.id));
    if (
      data.learningGoals &&
      new Set(data.learningGoals.map(g => g.id)).size !== data.learningGoals.length
    )
      ctx.addIssue({ code: "custom", message: "Duplicate learning goal identifiers" });
    data.transcript.turns.forEach((turn, i) => {
      if (
        turn.endMs <= turn.startMs ||
        (i > 0 && turn.startMs < data.transcript.turns[i - 1].startMs)
      ) {
        ctx.addIssue({
          code: "custom",
          message: "Turn timestamps must be ordered and have positive duration",
        });
      }
      if (
        turn.speaker.kind === "uncertain" &&
        turn.speaker.candidateStudentIds.some(candidateId => !students.has(candidateId))
      )
        ctx.addIssue({
          code: "custom",
          message: "Uncertain attribution candidates must reference the roster",
        });
      if (turn.speaker.kind === "student" && !students.has(turn.speaker.studentId)) {
        ctx.addIssue({
          code: "custom",
          message: "Student attribution must reference the session roster",
        });
      }
    });
    data.rubric.criteria.forEach(c => {
      if (
        c.noContributionScore !== undefined &&
        (c.kind !== "observable-participation" ||
          c.noContributionScore < c.minScore ||
          c.noContributionScore > c.maxScore)
      )
        ctx.addIssue({
          code: "custom",
          message:
            "No-contribution scoring requires an explicit observable-participation rule within range",
        });
      if (c.maxScore <= c.minScore)
        ctx.addIssue({
          code: "custom",
          message: "Each criterion needs a score range with maximum greater than minimum",
        });
    });
    data.documents.forEach(d =>
      unique(
        d.passages.map(p => p.id),
        "passage within document"
      )
    );
  });

export type AssessmentInputs = z.infer<typeof AssessmentInputsSchema>;
export const MAX_INPUT_BYTES = 2 * 1024 * 1024;

const ImportSchema = z.object({
  courseId: z.uuid().optional(),
  json: z.string().min(1).max(MAX_INPUT_BYTES),
});

export function parseImport(data: unknown) {
  const input = ImportSchema.safeParse(data);
  if (!input.success) throw new ValidationError(input.error.issues[0].message);
  if (new TextEncoder().encode(input.data.json).length > MAX_INPUT_BYTES)
    throw new ValidationError("Input file must be 2 MB or smaller");
  let json: unknown;
  try {
    json = JSON.parse(input.data.json);
  } catch {
    throw new ValidationError("Choose a valid JSON input file");
  }
  const parsed = AssessmentInputsSchema.safeParse(json);
  if (!parsed.success) throw new ValidationError(parsed.error.issues[0].message);
  return { courseId: input.data.courseId, inputs: parsed.data };
}

export function parseSessionId(data: unknown) {
  const parsed = z.object({ id: z.uuid() }).safeParse(data);
  if (!parsed.success) throw new ValidationError(parsed.error.issues[0].message);
  return parsed.data;
}
