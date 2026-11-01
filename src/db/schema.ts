import { sql } from "drizzle-orm";
import {
  pgTable,
  serial,
  text,
  timestamp,
  uuid,
  jsonb,
  index,
  integer,
  uniqueIndex,
  primaryKey,
} from "drizzle-orm/pg-core";
import { user } from "./auth-schema";
import type { DraftContent, WorkflowProgress } from "#/features/participation/schema";
import type { Investigation, Progress, SourceManifest } from "#/features/evidence/schema";
import type { AssessmentInputs } from "#/features/assessments/schema";

export const notes = pgTable("notes", {
  id: serial("id").primaryKey(),
  title: text("title").notNull(),
  userId: text("user_id")
    .notNull()
    .references(() => user.id, { onDelete: "cascade" }),
  createdAt: timestamp("created_at", { withTimezone: true }).defaultNow(),
});

export * from "./auth-schema";

// Course ownership is the professor authority for this first, single-professor slice.
export const courses = pgTable(
  "courses",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    professorId: text("professor_id")
      .notNull()
      .references(() => user.id, { onDelete: "cascade" }),
    title: text("title").notNull(),
    createdAt: timestamp("created_at", { withTimezone: true }).defaultNow().notNull(),
  },
  table => [index("courses_professor_idx").on(table.professorId)]
);

// Append-only inputs: future assessment runs can pin an exact session snapshot.
// Roster IDs are local domain identifiers, never Better Auth account foreign keys.
export const assessmentSessions = pgTable(
  "assessment_sessions",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    courseId: uuid("course_id")
      .notNull()
      .references(() => courses.id, { onDelete: "cascade" }),
    title: text("title").notNull(),
    inputs: jsonb("inputs").$type<AssessmentInputs>().notNull(),
    createdAt: timestamp("created_at", { withTimezone: true }).defaultNow().notNull(),
  },
  table => [index("assessment_sessions_course_idx").on(table.courseId)]
);

export const courseSourceVersions = pgTable(
  "course_source_versions",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    courseId: uuid("course_id")
      .notNull()
      .references(() => courses.id, { onDelete: "cascade" }),
    documentId: text("document_id").notNull(),
    version: text("version").notNull(),
    title: text("title").notNull(),
    source: text("source").notNull(),
    digest: text("digest").notNull(),
  },
  table => [
    uniqueIndex("course_source_version_unique").on(table.courseId, table.documentId, table.version),
  ]
);

export const coursePassages = pgTable(
  "course_passages",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    sourceId: uuid("source_id")
      .notNull()
      .references(() => courseSourceVersions.id, { onDelete: "cascade" }),
    passageKey: text("passage_key").notNull(),
    page: integer("page").notNull(),
    text: text("text").notNull(),
  },
  table => [
    uniqueIndex("source_passage_unique").on(table.sourceId, table.passageKey),
    index("passage_english_fts_idx").using("gin", sql`to_tsvector('english', ${table.text})`),
  ]
);

export const sessionSources = pgTable(
  "assessment_session_sources",
  {
    sessionId: uuid("session_id")
      .notNull()
      .references(() => assessmentSessions.id, { onDelete: "cascade" }),
    sourceId: uuid("source_id")
      .notNull()
      .references(() => courseSourceVersions.id, { onDelete: "cascade" }),
  },
  table => [primaryKey({ columns: [table.sessionId, table.sourceId] })]
);

export const evidenceRuns = pgTable(
  "evidence_runs",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    sessionId: uuid("session_id")
      .notNull()
      .references(() => assessmentSessions.id, { onDelete: "cascade" }),
    request: jsonb("request").$type<Investigation>().notNull(),
    manifest: jsonb("manifest").$type<SourceManifest>().notNull(),
    model: text("model").notNull(),
    promptVersion: text("prompt_version").notNull(),
    status: text("status", {
      enum: ["queued", "running", "completed", "needs_review", "failed"],
    }).notNull(),
    progress: jsonb("progress").$type<Progress>().notNull(),
    stopReason: text("stop_reason"),
    createdAt: timestamp("created_at", { withTimezone: true }).defaultNow().notNull(),
    deadlineAt: timestamp("deadline_at", { withTimezone: true }).notNull(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).defaultNow().notNull(),
  },
  table => [index("evidence_runs_session_idx").on(table.sessionId)]
);

export const participationRuns = pgTable(
  "participation_runs",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    sessionId: uuid("session_id")
      .notNull()
      .references(() => assessmentSessions.id, { onDelete: "cascade" }),
    status: text("status", {
      enum: ["running", "needs_review", "configuration_blocked", "failed"],
    }).notNull(),
    progress: jsonb("progress").$type<WorkflowProgress>().notNull(),
    manifest: jsonb("manifest")
      .$type<{
        transcriptVersion: string;
        rubricId: string;
        rubricVersion: string;
        model: string;
        promptVersion: string;
      }>()
      .notNull(),
    stopReason: text("stop_reason"),
    deadlineAt: timestamp("deadline_at", { withTimezone: true }).notNull(),
    createdAt: timestamp("created_at", { withTimezone: true }).defaultNow().notNull(),
  },
  table => [index("participation_runs_session_idx").on(table.sessionId)]
);

export const participationDrafts = pgTable(
  "participation_drafts",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    sessionId: uuid("session_id")
      .notNull()
      .references(() => assessmentSessions.id, { onDelete: "cascade" }),
    version: integer("version").notNull(),
    parentId: uuid("parent_id"),
    origin: text("origin", { enum: ["model", "professor"] }).notNull(),
    content: jsonb("content").$type<DraftContent>().notNull(),
    createdAt: timestamp("created_at", { withTimezone: true }).defaultNow().notNull(),
  },
  table => [uniqueIndex("participation_draft_version_unique").on(table.sessionId, table.version)]
);

export const rosterRecipients = pgTable(
  "roster_recipients",
  {
    sessionId: uuid("session_id")
      .notNull()
      .references(() => assessmentSessions.id, { onDelete: "cascade" }),
    studentId: text("student_id").notNull(),
    email: text("email").notNull(),
    revision: integer("revision").notNull(),
  },
  table => [primaryKey({ columns: [table.sessionId, table.studentId] })]
);

export const professorApprovals = pgTable(
  "professor_approvals",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    draftId: uuid("draft_id")
      .notNull()
      .references(() => participationDrafts.id, { onDelete: "cascade" }),
    professorId: text("professor_id")
      .notNull()
      .references(() => user.id, { onDelete: "cascade" }),
    digest: text("digest").notNull(),
    acknowledgement: text("acknowledgement").notNull(),
    issueIds: jsonb("issue_ids").$type<string[]>().notNull(),
    createdAt: timestamp("created_at", { withTimezone: true }).defaultNow().notNull(),
    invalidatedAt: timestamp("invalidated_at", { withTimezone: true }),
  },
  table => [
    uniqueIndex("one_current_approval_per_draft")
      .on(table.draftId)
      .where(sql`${table.invalidatedAt} is null`),
  ]
);

export const feedbackDeliveries = pgTable(
  "feedback_deliveries",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    draftId: uuid("draft_id")
      .notNull()
      .references(() => participationDrafts.id, { onDelete: "cascade" }),
    approvalId: uuid("approval_id")
      .notNull()
      .references(() => professorApprovals.id, { onDelete: "cascade" }),
    studentId: text("student_id").notNull(),
    recipient: text("recipient").notNull(),
    state: text("state", { enum: ["sending", "accepted", "rejected", "ambiguous"] }).notNull(),
    attempts: integer("attempts").notNull(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).defaultNow().notNull(),
  },
  table => [uniqueIndex("one_delivery_per_draft_student").on(table.draftId, table.studentId)]
);

export const feedbackDeliveryAttempts = pgTable(
  "feedback_delivery_attempts",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    deliveryId: uuid("delivery_id")
      .notNull()
      .references(() => feedbackDeliveries.id, { onDelete: "cascade" }),
    attempt: integer("attempt").notNull(),
    state: text("state", { enum: ["sending", "accepted", "rejected", "ambiguous"] }).notNull(),
    reason: text("reason"),
    messageId: text("message_id"),
    startedAt: timestamp("started_at", { withTimezone: true }).defaultNow().notNull(),
  },
  table => [uniqueIndex("delivery_attempt_unique").on(table.deliveryId, table.attempt)]
);
