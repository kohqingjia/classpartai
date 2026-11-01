import { createHash } from "node:crypto";
import { and, eq } from "drizzle-orm";
import type { db as Db } from "#/db";
import { courseSourceVersions, coursePassages, sessionSources } from "#/db/schema";
import type { AssessmentInputs } from "./schema";
import { UnprocessableEntityError } from "#/features/auth/session";

type Writer = Pick<typeof Db, "select" | "insert">;

export function sourceDigest(doc: AssessmentInputs["documents"][number]) {
  return createHash("sha256")
    .update(
      JSON.stringify([
        doc.id,
        doc.version,
        doc.title,
        doc.source,
        doc.passages.map(p => [p.id, p.page, p.text]),
      ])
    )
    .digest("hex");
}

// Called only after ownership is established, inside a transaction. Old snapshots are indexed lazily.
export async function indexSessionSources(
  database: Writer,
  courseId: string,
  sessionId: string,
  inputs: AssessmentInputs
) {
  for (const doc of inputs.documents) {
    const digest = sourceDigest(doc);
    // oxlint-disable-next-line no-await-in-loop -- source version and passage links are transactional and dependent
    await database
      .insert(courseSourceVersions)
      .values({
        courseId,
        documentId: doc.id,
        version: doc.version,
        title: doc.title,
        source: doc.source,
        digest,
      })
      .onConflictDoNothing();
    // oxlint-disable-next-line no-await-in-loop -- resolve the inserted or existing version before linking it
    const rows = await database
      .select()
      .from(courseSourceVersions)
      .where(
        and(
          eq(courseSourceVersions.courseId, courseId),
          eq(courseSourceVersions.documentId, doc.id),
          eq(courseSourceVersions.version, doc.version)
        )
      );
    const source = rows.at(0);
    if (!source || source.digest !== digest)
      throw new UnprocessableEntityError("Source version content mismatch; import a new version");
    // oxlint-disable-next-line no-await-in-loop -- passages depend on the resolved source ID
    await database
      .insert(coursePassages)
      .values(
        doc.passages.map(p => ({
          sourceId: source.id,
          passageKey: p.id,
          page: p.page,
          text: p.text,
        }))
      )
      .onConflictDoNothing();
    // oxlint-disable-next-line no-await-in-loop -- link only after the complete source version exists
    await database
      .insert(sessionSources)
      .values({ sessionId, sourceId: source.id })
      .onConflictDoNothing();
  }
}
