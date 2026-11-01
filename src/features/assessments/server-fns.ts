import { createServerFn } from "@tanstack/react-start";
import { requireSession } from "#/features/auth/session";
import { parseImport, parseSessionId } from "./schema";

export const listAssessmentSessions = createServerFn({ method: "GET" })
  .middleware([requireSession])
  .handler(async ({ context }) => {
    const [{ db }, { handleListSessions }] = await Promise.all([
      import("#/db"),
      import("./records.server"),
    ]);
    return handleListSessions(context.user, db, import.meta.env.DEV);
  });

export const getAssessmentSession = createServerFn({ method: "GET" })
  .middleware([requireSession])
  .validator(parseSessionId)
  .handler(async ({ data, context }) => {
    const [{ db }, { handleGetSession }] = await Promise.all([
      import("#/db"),
      import("./records.server"),
    ]);
    return handleGetSession(data.id, context.user, db, import.meta.env.DEV);
  });

export const importAssessmentSession = createServerFn({ method: "POST" })
  .middleware([requireSession])
  .validator(parseImport)
  .handler(async ({ data, context }) => {
    const [{ db }, { handleImportSession }] = await Promise.all([
      import("#/db"),
      import("./records.server"),
    ]);
    return handleImportSession(data, context.user, db, import.meta.env.DEV);
  });
