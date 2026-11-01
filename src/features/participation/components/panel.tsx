import { useState } from "react";
import { queryOptions, useMutation, useQuery } from "@tanstack/react-query";
import type { AssessmentInputs } from "#/features/assessments/schema";
import { Button } from "#/components/ui/button";
import { Input } from "#/components/ui/input";
import { Textarea } from "#/components/ui/textarea";
import { ProposalSchema } from "../schema";
import { observedCount, totals } from "../validation";
import {
  approveParticipationDraft,
  createUnassessedDraft,
  getParticipationReview,
  saveProfessorDraft,
  saveRosterRecipient,
  sendApprovedFeedback,
  startParticipationWorkflow,
} from "../server-fns";

function RecipientForm({
  sessionId,
  studentId,
  name,
  current,
  refreshed,
}: {
  sessionId: string;
  studentId: string;
  name: string;
  current?: string;
  refreshed: () => Promise<unknown>;
}) {
  const [email, setEmail] = useState(current ?? `${studentId}@example.invalid`);
  const save = useMutation({
    mutationFn: () => saveRosterRecipient({ data: { sessionId, studentId, email } }),
    onSuccess: refreshed,
  });
  return (
    <form
      className="my-3 space-y-2"
      onSubmit={e => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <label htmlFor={`recipient-${studentId}`}>{name} test recipient</label>
      <Input
        id={`recipient-${studentId}`}
        type="email"
        value={email}
        onChange={e => setEmail(e.target.value)}
      />
      <Button type="submit" variant="outline" disabled={save.isPending}>
        Save recipient {studentId}
      </Button>
      {save.error && <p role="alert">{save.error.message}</p>}
    </form>
  );
}

export function ParticipationPanel({
  sessionId,
  inputs,
}: {
  sessionId: string;
  inputs: AssessmentInputs;
}) {
  const review = useQuery(
    queryOptions({
      queryKey: ["participation-review", sessionId],
      queryFn: () => getParticipationReview({ data: { sessionId } }),
      refetchInterval: 2500,
      retry: false,
    })
  );
  const [editor, setEditor] = useState("");
  const [editingVersion, setEditingVersion] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const [ackDraftId, setAckDraftId] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const latest = review.data?.drafts.at(0);
  const activeApproval = review.data?.approvals.find(
    a => a.draftId === latest?.id && a.invalidatedAt === null
  );
  const refreshed = async () => {
    setAckDraftId(null);
    await review.refetch();
  };
  const create = useMutation({
    mutationFn: () => createUnassessedDraft({ data: { sessionId } }),
    onSuccess: refreshed,
  });
  const workflow = useMutation({
    mutationFn: () => startParticipationWorkflow({ data: { sessionId } }),
    onSettled: refreshed,
  });
  const save = useMutation({
    mutationFn: async () => {
      if (editingVersion === null) throw new Error("Load the latest version into the editor first");
      let raw: unknown;
      try {
        raw = JSON.parse(editor);
      } catch {
        throw new Error("Enter valid draft JSON");
      }
      const parsed = ProposalSchema.safeParse(raw);
      if (!parsed.success) throw new Error(parsed.error.issues[0].message);
      return saveProfessorDraft({
        data: { sessionId, expectedVersion: editingVersion, proposal: parsed.data, note },
      });
    },
    onSuccess: refreshed,
  });
  const approve = useMutation({
    mutationFn: () => {
      if (!latest) throw new Error("No draft to approve");
      return approveParticipationDraft({
        data: { sessionId, draftId: latest.id, acknowledge: ackDraftId === latest.id, reason },
      });
    },
    onSuccess: () => review.refetch(),
  });
  const deliver = useMutation({
    mutationFn: () => {
      if (!activeApproval) throw new Error("Explicit current-version approval is required");
      return sendApprovedFeedback({ data: { sessionId, approvalId: activeApproval.id } });
    },
    onSettled: () => review.refetch(),
  });
  const error =
    create.error ?? workflow.error ?? save.error ?? approve.error ?? deliver.error ?? review.error;
  return (
    <section
      className="mt-10 space-y-6 border-t pt-6"
      aria-label="Participation assessment and professor review"
    >
      <h2 className="text-2xl font-semibold">Provisional assessment and feedback</h2>
      <p>
        Scores and feedback remain provisional. The local-model coordinator chooses its route;
        missing configuration produces a blocked run, not fabricated results. No paid model fallback
        is available.
      </p>
      <div className="flex flex-wrap gap-3">
        <Button disabled={workflow.isPending} onClick={() => workflow.mutate()}>
          {workflow.isPending ? "Workflow active in this request…" : "Run participation workflow"}
        </Button>
        {!latest && (
          <Button variant="outline" disabled={create.isPending} onClick={() => create.mutate()}>
            Create unassessed professor draft
          </Button>
        )}
      </div>
      {error && <p role="alert">{error.message}</p>}
      {latest && (
        <section aria-label="Latest provisional draft" className="space-y-5">
          <h3 className="text-xl font-semibold">
            Version {latest.version} ·{" "}
            {latest.origin === "model" ? "Model proposal" : "Professor draft/edit"}
          </h3>
          <p>{latest.content.revisionNote}</p>
          {inputs.roster.map(student => {
            const total = totals(latest.content, inputs, student.id);
            const feedback = latest.content.feedback.find(f => f.studentId === student.id);
            return (
              <article key={student.id} className="space-y-2 rounded border p-4">
                <h4 className="font-semibold">{student.displayName}</h4>
                <p>
                  Observed attributed contributions: {observedCount(inputs, student.id)}. Counts are
                  separate from qualitative judgement.
                </p>
                <p>
                  Assessed subtotal: {total.knownSubtotal}; assessed criteria:{" "}
                  {total.assessedCriteria}/{total.totalCriteria}; total:{" "}
                  {total.total === null
                    ? "Unassessed/incomplete"
                    : `${total.total}/${total.maximum}`}
                  . {total.limitation}
                </p>
                {latest.content.findings
                  .filter(f => f.studentId === student.id)
                  .map(f => (
                    <section key={f.criterionId} className="border-l-2 pl-3">
                      <h5>
                        {inputs.rubric.criteria.find(c => c.id === f.criterionId)?.title}:{" "}
                        {f.status === "scored"
                          ? `Proposed ${f.score}`
                          : "Insufficient evidence — no score"}
                      </h5>
                      <p>{f.justification}</p>
                      <p>Limitations: {f.limitations.join("; ") || "None recorded"}</p>
                      {f.turnIds.map(id => (
                        <p key={id}>
                          Reviewed turn {id}: {inputs.transcript.turns.find(t => t.id === id)?.text}
                        </p>
                      ))}
                      {f.citations.map(c => {
                        const cite = review.data?.evidence
                          .find(e => e.id === c.evidenceRunId)
                          ?.bundle.citations.find(p => p.passageId === c.passageId);
                        return (
                          <blockquote key={`${c.evidenceRunId}-${c.passageId}`}>
                            {cite
                              ? `${cite.documentId} v${cite.version}, page ${cite.page}: ${cite.excerpt}`
                              : "Citation unavailable; review required"}
                          </blockquote>
                        );
                      })}
                    </section>
                  ))}
                <h5 className="font-semibold">Individual feedback draft</h5>
                {feedback ? (
                  <>
                    <p>{feedback.strengths}</p>
                    <p>Next step: {feedback.nextStep}</p>
                    <p>Limitations: {feedback.limitations.join("; ") || "None recorded"}</p>
                  </>
                ) : (
                  <p>No feedback draft yet. A draft is required for every roster student.</p>
                )}
              </article>
            );
          })}
          <section aria-label="Audit issues">
            <h4 className="font-semibold">Audit and uncertainty</h4>
            <p>
              {latest.content.audit.modelReviewed
                ? "Model audit completed; professor approval still required"
                : "Model audit pending/unavailable; explicit professor acknowledgement required"}
            </p>
            <ul>
              {latest.content.audit.issues.map(i => (
                <li key={i.id} className="mt-2">
                  {i.severity}: {i.detail} —{" "}
                  {activeApproval?.issueIds.includes(i.id)
                    ? "professor acknowledged"
                    : i.disposition}
                  {i.resolution ? `: ${i.resolution}` : ""}
                </li>
              ))}
            </ul>
            {activeApproval && <p>Professor acknowledgement: {activeApproval.acknowledgement}</p>}
          </section>
          <details>
            <summary>Professor edit — new version</summary>
            <Button
              variant="outline"
              onClick={() => {
                setEditor(
                  JSON.stringify(
                    { findings: latest.content.findings, feedback: latest.content.feedback },
                    null,
                    2
                  )
                );
                setEditingVersion(latest.version);
              }}
            >
              Load latest draft into editor
            </Button>
            <label htmlFor="professor-draft-json">Draft findings and feedback JSON</label>
            <Textarea
              id="professor-draft-json"
              rows={16}
              value={editor}
              onChange={e => setEditor(e.target.value)}
            />
            <label htmlFor="professor-edit-note">Reason for this edit</label>
            <Input id="professor-edit-note" value={note} onChange={e => setNote(e.target.value)} />
            <Button
              disabled={save.isPending || editingVersion === null || note.trim().length < 3}
              onClick={() => save.mutate()}
            >
              Save new professor version
            </Button>
            <p>
              Saving findings or feedback invalidates prior approvals. Stale edits are refused.
              Invalid scores, attribution and citations cannot be overridden.
            </p>
          </details>
        </section>
      )}
      <details>
        <summary>Authorised roster test recipients</summary>
        <p>
          Only example.invalid addresses are permitted. Recipients are separate roster records,
          never chosen by the model. Any change invalidates approvals.
        </p>
        {inputs.roster.map(s => {
          const recipient = review.data?.recipients.find(r => r.studentId === s.id);
          return (
            <RecipientForm
              key={`${s.id}:${recipient?.revision ?? 0}`}
              sessionId={sessionId}
              studentId={s.id}
              name={s.displayName}
              current={recipient?.email}
              refreshed={refreshed}
            />
          );
        })}
      </details>
      {latest && (
        <section className="space-y-3" aria-label="Professor approval and separate delivery">
          <h3 className="text-xl font-semibold">Professor approval</h3>
          <label className="flex gap-2">
            <input
              type="checkbox"
              checked={ackDraftId === latest.id}
              onChange={e => setAckDraftId(e.target.checked ? latest.id : null)}
            />
            I reviewed this exact version, its evidence, gaps and unresolved issues.
          </label>
          <label htmlFor="approval-reason">Acknowledgement / override reason</label>
          <Textarea id="approval-reason" value={reason} onChange={e => setReason(e.target.value)} />
          <Button disabled={approve.isPending} onClick={() => approve.mutate()}>
            Approve exact version {latest.version}
          </Button>
          <p>Approval is separate from sending. An auditor pass is not approval.</p>
          <h3 className="text-xl font-semibold">Development email delivery</h3>
          <Button
            variant="outline"
            disabled={!activeApproval || deliver.isPending}
            onClick={() => deliver.mutate()}
          >
            Send approved feedback to Mailpit
          </Button>
          <p>
            Local capture only. Accepted means accepted by SMTP, not confirmed inbox delivery.
            Accepted messages are not resent; ambiguous outcomes require manual investigation and
            are not retried.
          </p>
          <ul>
            {review.data?.deliveries.map(d => (
              <li key={d.id}>
                {d.studentId}: {d.state}; attempts: {d.attempts}
              </li>
            ))}
          </ul>
        </section>
      )}
      <details>
        <summary>Version and execution history</summary>
        <ul>
          {review.data?.drafts.map(d => (
            <li key={d.id}>
              Version {d.version} · {d.origin} · {d.content.revisionNote}
            </li>
          ))}
        </ul>
        {review.data?.runs.map(r => (
          <article key={r.id} className="my-4 rounded border p-3">
            <h4>
              {r.status}: {r.stopReason ?? "Request active"}
            </h4>
            <p>
              Run {r.id} · model calls {r.progress.modelCalls}; tool calls {r.progress.toolCalls};
              tokens {r.progress.tokens} ({r.progress.usageKind})
            </p>
            {r.progress.actions.map(a => (
              <p key={a.id}>
                {a.tool} ({a.outcome}): {a.summary}
              </p>
            ))}
          </article>
        ))}
      </details>
    </section>
  );
}
