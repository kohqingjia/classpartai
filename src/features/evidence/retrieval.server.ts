import { and, desc, eq, sql } from "drizzle-orm";
import type { z } from "zod";
import type { db as Db } from "#/db";
import {
  assessmentSessions,
  courses,
  coursePassages,
  courseSourceVersions,
  sessionSources,
} from "#/db/schema";
import type { SessionUser } from "#/features/auth/session";
import { NotFoundError } from "#/features/auth/session";
import { handleGetSession } from "#/features/assessments/records.server";
import { indexSessionSources } from "#/features/assessments/sources.server";
import type { FetchSchema, Passage, SearchSchema } from "./schema";

type Database = typeof Db;
export interface RetrievalScope {
  sessionId: string;
  user: SessionUser;
  allowFixtures: boolean;
}

export async function prepareSources(scope: RetrievalScope, database: Database) {
  const session = await handleGetSession(
    scope.sessionId,
    scope.user,
    database,
    scope.allowFixtures
  );
  const linked = await database
    .select({ sourceId: sessionSources.sourceId })
    .from(sessionSources)
    .where(eq(sessionSources.sessionId, session.id));
  if (linked.length !== session.inputs.documents.length) {
    await database.transaction(tx =>
      indexSessionSources(tx, session.courseId, session.id, session.inputs)
    );
  }
  return session;
}

// Re-check ownership in every retrieval SQL query, not just at the entry point or in a prompt.
function scopedQuery(database: Database) {
  return database
    .select({
      passageId: coursePassages.id,
      documentId: courseSourceVersions.documentId,
      version: courseSourceVersions.version,
      title: courseSourceVersions.title,
      source: courseSourceVersions.source,
      passageKey: coursePassages.passageKey,
      page: coursePassages.page,
      text: coursePassages.text,
    })
    .from(coursePassages)
    .innerJoin(courseSourceVersions, eq(courseSourceVersions.id, coursePassages.sourceId))
    .innerJoin(sessionSources, eq(sessionSources.sourceId, courseSourceVersions.id))
    .innerJoin(assessmentSessions, eq(assessmentSessions.id, sessionSources.sessionId))
    .innerJoin(courses, eq(courses.id, assessmentSessions.courseId));
}
function restriction(scope: RetrievalScope) {
  return and(
    eq(assessmentSessions.id, scope.sessionId),
    eq(courses.professorId, scope.user.id),
    eq(courseSourceVersions.courseId, courses.id),
    scope.allowFixtures ? undefined : sql`${assessmentSessions.inputs}->>'provenance' = 'reviewed'`
  );
}

export async function searchPassages(
  scope: RetrievalScope,
  args: z.infer<typeof SearchSchema>,
  database: Database
): Promise<Array<Passage & { rankPosition: number }>> {
  const query = sql`websearch_to_tsquery('english', ${args.query})`;
  const vector = sql`to_tsvector('english', ${coursePassages.text})`;
  const rows = await scopedQuery(database)
    .where(
      and(
        restriction(scope),
        sql`${vector} @@ ${query}`,
        args.documentId === null ? undefined : eq(courseSourceVersions.documentId, args.documentId),
        args.version === null ? undefined : eq(courseSourceVersions.version, args.version)
      )
    )
    .orderBy(desc(sql`ts_rank_cd(${vector}, ${query})`), coursePassages.id)
    .limit(args.limit);
  // Search returns a bounded preview. Rank determines order only; it is not confidence.
  return rows.map((r, i) =>
    Object.assign({}, r, {
      text: r.text.slice(0, 1200),
      offset: 0,
      truncated: r.text.length > 1200,
      rankPosition: i + 1,
    })
  );
}

export async function fetchPassage(
  scope: RetrievalScope,
  args: z.infer<typeof FetchSchema>,
  database: Database
): Promise<Passage> {
  const rows = await scopedQuery(database)
    .where(and(restriction(scope), eq(coursePassages.id, args.passageId)))
    .limit(1);
  const row = rows.at(0);
  if (!row) throw new NotFoundError("Source passage not found");
  return {
    ...row,
    text: row.text.slice(args.offset, args.offset + 6000),
    offset: args.offset,
    truncated: row.text.length > args.offset + 6000,
  };
}
