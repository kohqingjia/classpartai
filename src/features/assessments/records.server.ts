import { indexSessionSources } from "./sources.server";
import { isDeepStrictEqual } from "node:util";
import { and, desc, eq, sql } from "drizzle-orm";
import type { db as Db } from "#/db";
import { assessmentSessions, courses } from "#/db/schema";
import { NotFoundError, UnprocessableEntityError } from "#/features/auth/session";
import type { SessionUser } from "#/features/auth/session";
import type { parseImport } from "./schema";

type Database = typeof Db;

export async function handleListSessions(
  user: SessionUser,
  database: Database,
  allowFixtures: boolean
) {
  return database
    .select({
      id: assessmentSessions.id,
      title: assessmentSessions.title,
      courseId: courses.id,
      courseTitle: courses.title,
      createdAt: assessmentSessions.createdAt,
    })
    .from(assessmentSessions)
    .innerJoin(courses, eq(courses.id, assessmentSessions.courseId))
    .where(
      and(
        eq(courses.professorId, user.id),
        allowFixtures ? undefined : sql`${assessmentSessions.inputs}->>'provenance' = 'reviewed'`
      )
    )
    .orderBy(desc(assessmentSessions.createdAt));
}

export async function handleGetSession(
  id: string,
  user: SessionUser,
  database: Database,
  allowFixtures: boolean
) {
  const rows = await database
    .select({
      id: assessmentSessions.id,
      courseId: courses.id,
      courseTitle: courses.title,
      inputs: assessmentSessions.inputs,
      createdAt: assessmentSessions.createdAt,
    })
    .from(assessmentSessions)
    .innerJoin(courses, eq(courses.id, assessmentSessions.courseId))
    .where(
      and(
        eq(assessmentSessions.id, id),
        eq(courses.professorId, user.id),
        allowFixtures ? undefined : sql`${assessmentSessions.inputs}->>'provenance' = 'reviewed'`
      )
    );
  const row = rows.at(0);
  if (!row) throw new NotFoundError("Assessment session not found");
  return row;
}

export async function handleImportSession(
  data: ReturnType<typeof parseImport>,
  user: SessionUser,
  database: Database,
  allowFixtures: boolean
) {
  if (data.inputs.provenance === "fictional-development" && !allowFixtures) {
    throw new UnprocessableEntityError(
      "Fictional development fixtures can only be imported in development"
    );
  }
  return database.transaction(async tx => {
    let courseId = data.courseId;
    if (courseId) {
      const ownedRows = await tx
        .select()
        .from(courses)
        .where(and(eq(courses.id, courseId), eq(courses.professorId, user.id)))
        .for("update");
      const owned = ownedRows.at(0);
      if (!owned) throw new NotFoundError("Course not found");
      if (owned.title !== data.inputs.courseTitle)
        throw new UnprocessableEntityError("Input course title must match the selected course");
      const previousSessions = await tx
        .select({ inputs: assessmentSessions.inputs })
        .from(assessmentSessions)
        .where(eq(assessmentSessions.courseId, courseId));
      const previous = previousSessions.at(0);
      if (previous && previous.inputs.provenance !== data.inputs.provenance) {
        throw new UnprocessableEntityError(
          "Fictional fixtures and reviewed inputs must use separate courses"
        );
      }
      for (const session of previousSessions) {
        const prior = session.inputs.rubric;
        if (
          prior.id === data.inputs.rubric.id &&
          prior.version === data.inputs.rubric.version &&
          !isDeepStrictEqual(prior, data.inputs.rubric)
        ) {
          throw new UnprocessableEntityError("Changed rubric content requires a new version");
        }
        for (const doc of data.inputs.documents) {
          const original = session.inputs.documents.find(
            d => d.id === doc.id && d.version === doc.version
          );
          if (original && !isDeepStrictEqual(original, doc)) {
            throw new UnprocessableEntityError(
              "Changed course document content requires a new version"
            );
          }
        }
      }
    } else {
      const [created] = await tx
        .insert(courses)
        .values({ title: data.inputs.courseTitle, professorId: user.id })
        .returning();
      courseId = created.id;
    }
    const [created] = await tx
      .insert(assessmentSessions)
      // Force a text parameter before parsing JSONB: Bun SQL otherwise JSON-encodes
      // Drizzle's already-stringified JSON value a second time.
      .values({
        courseId,
        title: data.inputs.sessionTitle,
        inputs: sql`cast(${JSON.stringify(data.inputs)} as text)::jsonb`,
      })
      .returning({ id: assessmentSessions.id });
    await indexSessionSources(tx, courseId, created.id, data.inputs);
    return created;
  });
}
