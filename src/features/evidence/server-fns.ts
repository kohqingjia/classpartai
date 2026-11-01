import { createServerFn } from "@tanstack/react-start";
import { requireSession } from "#/features/auth/session";
import {
  parseEvidenceScope,
  parseInvestigation,
  parsePassageRequest,
  parseSearchRequest,
} from "./schema";

export const searchCoursePassages = createServerFn({ method: "POST" })
  .middleware([requireSession])
  .validator(parseSearchRequest)
  .handler(async ({ data, context }) => {
    const [{ db }, { prepareSources, searchPassages }] = await Promise.all([
      import("#/db"),
      import("./retrieval.server"),
    ]);
    const scope = {
      sessionId: data.sessionId,
      user: context.user,
      allowFixtures: import.meta.env.DEV,
    };
    await prepareSources(scope, db);
    return searchPassages(scope, data.search, db);
  });
export const getSourcePassage = createServerFn({ method: "GET" })
  .middleware([requireSession])
  .validator(parsePassageRequest)
  .handler(async ({ data, context }) => {
    const [{ db }, { prepareSources, fetchPassage }] = await Promise.all([
      import("#/db"),
      import("./retrieval.server"),
    ]);
    const scope = {
      sessionId: data.sessionId,
      user: context.user,
      allowFixtures: import.meta.env.DEV,
    };
    await prepareSources(scope, db);
    return fetchPassage(scope, data.passage, db);
  });
export const getEvidenceRuns = createServerFn({ method: "GET" })
  .middleware([requireSession])
  .validator(parseEvidenceScope)
  .handler(async ({ data, context }) => {
    const [{ db }, { listEvidenceRuns }] = await Promise.all([
      import("#/db"),
      import("./runs.server"),
    ]);
    return listEvidenceRuns(
      { sessionId: data.sessionId, user: context.user, allowFixtures: import.meta.env.DEV },
      db
    );
  });
export const investigateEvidence = createServerFn({ method: "POST" })
  .middleware([requireSession])
  .validator(parseInvestigation)
  .handler(async ({ data, context }) => {
    const [{ db }, { startInvestigation }, { getRequest }] = await Promise.all([
      import("#/db"),
      import("./runs.server"),
      import("@tanstack/react-start/server"),
    ]);
    return startInvestigation(
      { sessionId: data.sessionId, user: context.user, allowFixtures: import.meta.env.DEV },
      data,
      db,
      getRequest().signal
    );
  });
