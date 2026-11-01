/* oxlint-disable no-await-in-loop -- Persist each individual delivery claim before SMTP and its outcome afterwards. */
import { z } from "zod";
import { and, desc, eq, isNull } from "drizzle-orm";
import type { db as Db } from "#/db";
import {
  assessmentSessions,
  feedbackDeliveries,
  feedbackDeliveryAttempts,
  participationDrafts,
  professorApprovals,
  rosterRecipients,
} from "#/db/schema";
import { UnprocessableEntityError } from "#/features/auth/session";
import { handleGetSession } from "#/features/assessments/records.server";
import type { RetrievalScope } from "#/features/evidence/retrieval.server";
import { env } from "#/env";
import { sendFeedbackToCapture } from "#/lib/mailer.server";
import { approvalDigest, developmentRecipient, reviewState } from "./records.server";

type Database = typeof Db;
export async function deliverApproved(
  scope: RetrievalScope,
  approvalId: string,
  database: Database,
  transport = sendFeedbackToCapture
) {
  const session = await handleGetSession(
    scope.sessionId,
    scope.user,
    database,
    scope.allowFixtures
  );
  if (env.FEEDBACK_DELIVERY !== "mailpit")
    throw new UnprocessableEntityError(
      "Enable local Mailpit capture explicitly; paid email is never used"
    );
  await reviewState(scope, database);
  const results: Array<{ studentId: string; state: string }> = [];
  let attempted = 0;
  for (const student of session.inputs.roster) {
    if (attempted >= 5) break;
    const claim = await database.transaction(async tx => {
      await tx
        .select({ id: assessmentSessions.id })
        .from(assessmentSessions)
        .where(eq(assessmentSessions.id, session.id))
        .for("update");
      const draft = (
        await tx
          .select()
          .from(participationDrafts)
          .where(eq(participationDrafts.sessionId, session.id))
          .orderBy(desc(participationDrafts.version))
          .limit(1)
      ).at(0);
      if (!draft) throw new UnprocessableEntityError("No approved draft");
      const approval = (
        await tx
          .select()
          .from(professorApprovals)
          .where(
            and(
              eq(professorApprovals.id, approvalId),
              eq(professorApprovals.draftId, draft.id),
              eq(professorApprovals.professorId, scope.user.id),
              isNull(professorApprovals.invalidatedAt)
            )
          )
          .limit(1)
      ).at(0);
      const recipients = await tx
        .select()
        .from(rosterRecipients)
        .where(eq(rosterRecipients.sessionId, session.id));
      if (!approval || approval.digest !== approvalDigest(draft.content, recipients))
        throw new UnprocessableEntityError(
          "Approval is missing, invalidated or does not match the exact current version and recipients"
        );
      const recipient = recipients.find(r => r.studentId === student.id);
      if (!recipient) throw new UnprocessableEntityError("Missing roster test recipient");
      developmentRecipient(recipient.email);
      const feedback = draft.content.feedback.find(f => f.studentId === student.id);
      if (!feedback) throw new UnprocessableEntityError("Missing approved individual feedback");
      const previous = (
        await tx
          .select()
          .from(feedbackDeliveries)
          .where(
            and(
              eq(feedbackDeliveries.draftId, draft.id),
              eq(feedbackDeliveries.studentId, student.id)
            )
          )
          .limit(1)
      ).at(0);
      if (previous && previous.state !== "rejected") return { skipped: previous.state };
      const attempt = (previous?.attempts ?? 0) + 1;
      if (attempt > 3)
        throw new UnprocessableEntityError(
          "Delivery retry limit reached; inspect the capture service"
        );
      let deliveryId: string;
      if (previous) {
        deliveryId = previous.id;
        await tx
          .update(feedbackDeliveries)
          .set({
            approvalId: approval.id,
            recipient: recipient.email,
            state: "sending",
            attempts: attempt,
            updatedAt: new Date(),
          })
          .where(eq(feedbackDeliveries.id, deliveryId));
      } else {
        const [delivery] = await tx
          .insert(feedbackDeliveries)
          .values({
            draftId: draft.id,
            approvalId: approval.id,
            studentId: student.id,
            recipient: recipient.email,
            state: "sending",
            attempts: attempt,
          })
          .returning({ id: feedbackDeliveries.id });
        deliveryId = delivery.id;
      }
      const [record] = await tx
        .insert(feedbackDeliveryAttempts)
        .values({ deliveryId, attempt, state: "sending" })
        .returning({ id: feedbackDeliveryAttempts.id });
      const resources = feedback.citations.map(c => `${c.evidenceRunId}/${c.passageId}`).join("\n");
      const text = `${feedback.strengths}\n\nNext step: ${feedback.nextStep}\n\nLimitations: ${feedback.limitations.join("; ")}\n\nCourse references:\n${resources}\n\nProfessor-reviewed feedback, version ${draft.version}.`;
      return {
        deliveryId,
        attemptId: record.id,
        recipient: recipient.email,
        text,
        version: draft.version,
        attempt,
      };
    });
    if ("skipped" in claim) {
      results.push({ studentId: student.id, state: claim.skipped ?? "unknown" });
      continue;
    }
    attempted++;
    let state: "accepted" | "rejected" | "ambiguous" = "ambiguous";
    let reason: string | null = null;
    let messageId: string | null = null;
    try {
      const sent = await transport(
        claim.recipient,
        `ClassPart AI feedback — version ${claim.version}`,
        claim.text,
        `<classpart-${claim.deliveryId}-${claim.attempt}@example.invalid>`
      );
      state = "accepted";
      messageId = sent.messageId;
    } catch (error) {
      const parsedError = z
        .object({
          code: z.string().optional(),
          responseCode: z.number().optional(),
          message: z.string().optional(),
        })
        .safeParse(error);
      const smtp = parsedError.success ? parsedError.data : {};
      const rejected =
        smtp.code === "ECONNREFUSED" ||
        (typeof smtp.responseCode === "number" && smtp.responseCode >= 400) ||
        smtp.message === "Local capture delivery is disabled" ||
        smtp.message === "Feedback requires loopback Mailpit SMTP on port 1025";
      state = rejected ? "rejected" : "ambiguous";
      reason = rejected
        ? "Mail service did not accept; explicit retry permitted"
        : "SMTP acceptance unknown; do not retry automatically";
    }
    await database.transaction(async tx => {
      await tx
        .update(feedbackDeliveries)
        .set({ state, updatedAt: new Date() })
        .where(
          and(eq(feedbackDeliveries.id, claim.deliveryId), eq(feedbackDeliveries.state, "sending"))
        );
      await tx
        .update(feedbackDeliveryAttempts)
        .set({ state, reason, messageId })
        .where(
          and(
            eq(feedbackDeliveryAttempts.id, claim.attemptId),
            eq(feedbackDeliveryAttempts.state, "sending")
          )
        );
    });
    results.push({ studentId: student.id, state });
  }
  return results;
}
