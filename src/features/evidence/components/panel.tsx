import { useState } from "react";
import { queryOptions, useMutation, useQuery } from "@tanstack/react-query";
import type { AssessmentInputs } from "#/features/assessments/schema";
import { Button } from "#/components/ui/button";
import { Input } from "#/components/ui/input";
import { Textarea } from "#/components/ui/textarea";
import {
  getEvidenceRuns,
  getSourcePassage,
  investigateEvidence,
  searchCoursePassages,
} from "../server-fns";

const toggle = (ids: string[], id: string) =>
  ids.includes(id) ? ids.filter(value => value !== id) : [...ids, id];

export function EvidencePanel({
  sessionId,
  inputs,
}: {
  sessionId: string;
  inputs: AssessmentInputs;
}) {
  const [query, setQuery] = useState("");
  const [question, setQuestion] = useState("");
  const [turnIds, setTurnIds] = useState<string[]>([]);
  const [criterionIds, setCriterionIds] = useState<string[]>([]);
  const runs = useQuery(
    queryOptions({
      queryKey: ["evidence-runs", sessionId],
      queryFn: () => getEvidenceRuns({ data: { sessionId } }),
      refetchInterval: 2500,
      retry: false,
    })
  );
  const search = useMutation({
    mutationFn: () =>
      searchCoursePassages({
        data: { sessionId, search: { query, documentId: null, version: null, limit: 5 } },
      }),
  });
  const detail = useMutation({
    mutationFn: (passageId: string) =>
      getSourcePassage({ data: { sessionId, passage: { passageId, offset: 0 } } }),
  });
  const investigate = useMutation({
    mutationFn: () => investigateEvidence({ data: { sessionId, question, turnIds, criterionIds } }),
    onSettled: () => runs.refetch(),
  });
  return (
    <section className="mt-10 space-y-6 border-t pt-6" aria-label="Course evidence">
      <h2 className="text-2xl font-semibold">Course evidence investigation</h2>
      <p className="text-sm">
        English lexical full-text retrieval. Paraphrases may not match. Source text is separate from
        model interpretation. No participation scores or feedback delivery.
      </p>
      <form
        className="space-y-2"
        onSubmit={e => {
          e.preventDefault();
          search.mutate();
          detail.reset();
        }}
      >
        <label htmlFor="course-query">Search authorised course passages</label>
        <Input
          id="course-query"
          value={query}
          maxLength={240}
          onChange={e => setQuery(e.target.value)}
        />
        <Button type="submit" disabled={!query.trim() || search.isPending}>
          Search passages
        </Button>
      </form>
      {search.error && <p role="alert">{search.error.message}</p>}
      {search.data && search.data.length === 0 && (
        <p>No lexical matches. Try different terms; this does not establish absence of evidence.</p>
      )}
      {search.data?.map(p => (
        <article key={p.passageId} className="rounded border p-3">
          <h3 className="font-semibold">
            {p.title} — {p.documentId}, version {p.version}, page {p.page}
          </h3>
          <p className="text-sm">
            Source: {p.source} · Passage: {p.passageKey} · ID: {p.passageId}
          </p>
          <blockquote>{p.text}</blockquote>
          <Button variant="outline" onClick={() => detail.mutate(p.passageId)}>
            Fetch passage {p.passageKey}
          </Button>
        </article>
      ))}
      {detail.error && <p role="alert">{detail.error.message}</p>}
      {detail.data && (
        <blockquote className="rounded border p-3">
          <p>
            Retrieved source window · {detail.data.documentId}/{detail.data.passageKey} · Page{" "}
            {detail.data.page}
            {detail.data.truncated ? " · More context exists" : ""}
          </p>
          {detail.data.text}
        </blockquote>
      )}
      <form
        className="space-y-3"
        onSubmit={e => {
          e.preventDefault();
          investigate.mutate();
        }}
      >
        <label htmlFor="evidence-question">Participation question for investigation</label>
        <Textarea
          id="evidence-question"
          maxLength={1500}
          value={question}
          onChange={e => setQuestion(e.target.value)}
        />
        <fieldset>
          <legend>Select relevant reviewed turns (maximum eight)</legend>
          {inputs.transcript.turns.map(t => (
            <label key={t.id} className="mr-4 inline-flex gap-2">
              <input
                type="checkbox"
                checked={turnIds.includes(t.id)}
                disabled={!turnIds.includes(t.id) && turnIds.length >= 8}
                onChange={() => setTurnIds(toggle(turnIds, t.id))}
              />
              {t.id}
            </label>
          ))}
        </fieldset>
        <fieldset>
          <legend>Select rubric context (maximum six criteria)</legend>
          {inputs.rubric.criteria.map(c => (
            <label key={c.id} className="mr-4 inline-flex gap-2">
              <input
                type="checkbox"
                checked={criterionIds.includes(c.id)}
                disabled={!criterionIds.includes(c.id) && criterionIds.length >= 6}
                onChange={() => setCriterionIds(toggle(criterionIds, c.id))}
              />
              {c.title}
            </label>
          ))}
        </fieldset>
        <p className="text-sm">
          This sends the question, selected transcript/rubric context and retrieved course passages
          to the configured local model. Run only with materials you may send to that provider.
          Execution uses this HTTP request, not a durable background job.
        </p>
        <Button
          type="submit"
          disabled={
            investigate.isPending ||
            question.trim().length < 5 ||
            !turnIds.length ||
            !criterionIds.length
          }
        >
          {investigate.isPending ? "Investigating in this request…" : "Investigate evidence"}
        </Button>
        {investigate.error && <p role="alert">{investigate.error.message}</p>}
      </form>
      <section aria-label="Evidence run history" className="space-y-4">
        <h3 className="text-xl font-semibold">Recent investigations</h3>
        {runs.error && <p role="alert">{runs.error.message}</p>}
        {runs.data?.length === 0 && <p>No investigations yet.</p>}
        {runs.data?.map(run => (
          <article key={run.id} className="space-y-2 rounded border p-4">
            <h4 className="font-semibold">
              {run.status} · {run.stopReason ?? "Request active"}
            </h4>
            <p className="text-sm">
              Run {run.id} · {run.model} · {run.promptVersion}
            </p>
            <p>{run.request.question}</p>
            {run.stopReason === "provider_not_configured" && (
              <p>
                Live local-model execution blocked: configure a loopback LOCAL_MODEL, then
                explicitly start a new investigation.
              </p>
            )}
            <p className="text-sm">
              Model calls: {run.progress.modelCalls}; tool calls: {run.progress.toolCalls}; reported
              tokens: {run.progress.tokens}; returned characters: {run.progress.returnedCharacters}
            </p>
            <ol>
              {run.progress.actions.map(a => (
                <li key={a.id} className="mt-2">
                  <strong>
                    {a.tool} ({a.outcome})
                  </strong>{" "}
                  — {a.summary}
                  <pre className="overflow-auto text-xs">{a.arguments}</pre>
                  <p className="text-xs">References: {a.resultReferences.join(", ") || "None"}</p>
                </li>
              ))}
            </ol>
            {run.progress.bundle && (
              <section aria-label="Evidence bundle">
                <p>
                  {run.progress.bundle.status}: {run.progress.bundle.explanation}
                </p>
                <p>Transcript turns: {run.progress.bundle.turnIds.join(", ")}</p>
                <p className="text-sm">
                  Exact authorised citations checked; factual support and relevance are model
                  proposals requiring professor review.
                </p>
                {run.progress.bundle.citations.map(c => (
                  <blockquote
                    key={`${c.passageId}:${c.excerpt}:${c.relationship}`}
                    className="mt-2 border-l-2 pl-3"
                  >
                    <p>
                      {c.documentId} v{c.version} · {c.passageKey} · Page {c.page} ·{" "}
                      {c.relationship}
                    </p>
                    <p>Source: {c.source}</p>
                    <p>“{c.excerpt}”</p>
                    <p>Model-proposed relevance: {c.relevance}</p>
                  </blockquote>
                ))}
                <p>
                  Conflicts: {run.progress.bundle.conflicts.join("; ") || "None reported by model"}
                </p>
                <p>
                  Unresolved gaps: {run.progress.bundle.gaps.join("; ") || "None reported by model"}
                </p>
              </section>
            )}
          </article>
        ))}
      </section>
    </section>
  );
}
