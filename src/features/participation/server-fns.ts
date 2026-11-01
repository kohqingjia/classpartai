import { createServerFn } from "@tanstack/react-start";
import { requireSession } from "#/features/auth/session";
import {
  parseApproval,
  parseDelivery,
  parseDraftEdit,
  parseParticipationScope,
  parseRecipient,
} from "./schema";

export const getParticipationReview = createServerFn({ method: "GET" })
  .middleware([requireSession])
  .validator(parseParticipationScope)
  .handler(async ({ data, context }) => {
    const [{ db }, { reviewState }] = await Promise.all([
      import("#/db"),
      import("./records.server"),
    ]);
    return reviewState(
      { sessionId: data.sessionId, user: context.user, allowFixtures: import.meta.env.DEV },
      db
    );
  });
export const createUnassessedDraft = createServerFn({ method: "POST" })
  .middleware([requireSession])
  .validator(parseParticipationScope)
  .handler(async ({ data, context }) => {
    const [{ db }, { createProfessorDraft }] = await Promise.all([
      import("#/db"),
      import("./records.server"),
    ]);
    const created = await createProfessorDraft(
      { sessionId: data.sessionId, user: context.user, allowFixtures: import.meta.env.DEV },
      db
    );
    return { id: created.id };
  });
export const saveProfessorDraft = createServerFn({ method: "POST" })
  .middleware([requireSession])
  .validator(parseDraftEdit)
  .handler(async ({ data, context }) => {
    const [{ db }, { appendDraft }] = await Promise.all([
      import("#/db"),
      import("./records.server"),
    ]);
    const created = await appendDraft(
      { sessionId: data.sessionId, user: context.user, allowFixtures: import.meta.env.DEV },
      data.proposal,
      "professor",
      data.note,
      db,
      data.expectedVersion
    );
    return { id: created.id };
  });
export const saveRosterRecipient = createServerFn({ method: "POST" })
  .middleware([requireSession])
  .validator(parseRecipient)
  .handler(async ({ data, context }) => {
    const [{ db }, { setRecipient }] = await Promise.all([
      import("#/db"),
      import("./records.server"),
    ]);
    return setRecipient(
      { sessionId: data.sessionId, user: context.user, allowFixtures: import.meta.env.DEV },
      data.studentId,
      data.email,
      db
    );
  });
export const approveParticipationDraft = createServerFn({ method: "POST" })
  .middleware([requireSession])
  .validator(parseApproval)
  .handler(async ({ data, context }) => {
    const [{ db }, { approveDraft }] = await Promise.all([
      import("#/db"),
      import("./records.server"),
    ]);
    return approveDraft(
      { sessionId: data.sessionId, user: context.user, allowFixtures: import.meta.env.DEV },
      data.draftId,
      data.acknowledge,
      data.reason,
      db
    );
  });
export const sendApprovedFeedback = createServerFn({ method: "POST" })
  .middleware([requireSession])
  .validator(parseDelivery)
  .handler(async ({ data, context }) => {
    const [{ db }, { deliverApproved }] = await Promise.all([
      import("#/db"),
      import("./delivery.server"),
    ]);
    return deliverApproved(
      { sessionId: data.sessionId, user: context.user, allowFixtures: import.meta.env.DEV },
      data.approvalId,
      db
    );
  });
export const startParticipationWorkflow = createServerFn({ method: "POST" })
  .middleware([requireSession])
  .validator(parseParticipationScope)
  .handler(async ({ data, context }) => {
    const [{ db }, { coordinate }, { getRequest }] = await Promise.all([
      import("#/db"),
      import("./coordinator.server"),
      import("@tanstack/react-start/server"),
    ]);
    return coordinate(
      { sessionId: data.sessionId, user: context.user, allowFixtures: import.meta.env.DEV },
      db,
      getRequest().signal
    );
  });
