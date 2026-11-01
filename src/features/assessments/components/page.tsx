import { ParticipationPanel } from "#/features/participation/components/panel";
import { EvidencePanel } from "#/features/evidence/components/panel";
import { useState } from "react";
import { getRouteApi, useRouter } from "@tanstack/react-router";
import { queryOptions, skipToken, useMutation, useQuery } from "@tanstack/react-query";
import { Page } from "#/components/custom/page";
import { Button } from "#/components/ui/button";
import { Input } from "#/components/ui/input";
import { getAssessmentSession, importAssessmentSession } from "../server-fns";
import { MAX_INPUT_BYTES } from "../schema";

const routeApi = getRouteApi("/_authenticated/assessments");

export function AssessmentsPage() {
  const { sessions } = routeApi.useLoaderData();
  const router = useRouter();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [courseId, setCourseId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const selected = useQuery(
    queryOptions({
      queryKey: ["assessment-inputs", selectedId],
      queryFn:
        selectedId === null ? skipToken : () => getAssessmentSession({ data: { id: selectedId } }),
      enabled: selectedId !== null,
      retry: false,
    })
  );
  const upload = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error("Choose a reviewed session JSON file");
      if (file.size > MAX_INPUT_BYTES) throw new Error("Input file must be 2 MB or smaller");
      return importAssessmentSession({
        data: { json: await file.text(), courseId: courseId || undefined },
      });
    },
    onSuccess: async result => {
      setSelectedId(result.id);
      await router.invalidate();
    },
  });
  const courses = [
    ...new Map(sessions.map(s => [s.courseId, { id: s.courseId, title: s.courseTitle }])).values(),
  ];
  const inputs = selected.data?.inputs;
  const rosterNames = new Map(inputs?.roster.map(s => [s.id, s.displayName]));

  return (
    <Page
      eyebrow="Professor"
      title="Assessment inputs"
      description="Load reviewed inputs and inspect the evidence available for an assessment session."
    >
      <p className="mt-4 text-sm text-muted-foreground">
        Reviewed inputs remain read-only. Assessment proposals and feedback remain provisional until
        professor review.
      </p>
      <section className="mt-8" aria-labelledby="import-heading">
        <h2 id="import-heading" className="text-xl font-semibold">
          Import reviewed session
        </h2>
        <p className="mt-2 text-sm">
          Import a JSON snapshot containing a roster, reviewed transcript, versioned rubric and
          course passages. Only import materials you are authorised to use for this course.
        </p>
        {import.meta.env.DEV && (
          <p className="mt-2 text-sm">
            For a fictional example, select tests/fixtures/assessment-fictional.json from this
            repository. It imports into a separate, labelled course.
          </p>
        )}
        <form
          className="mt-4 space-y-3"
          onSubmit={e => {
            e.preventDefault();
            upload.mutate();
          }}
        >
          <label htmlFor="assessment-course" className="block">
            Course
            <select
              id="assessment-course"
              className="ml-3 rounded border bg-background p-2"
              value={courseId}
              onChange={e => setCourseId(e.target.value)}
            >
              <option value="">Create a course from this file</option>
              {courses.map(c => (
                <option key={c.id} value={c.id}>
                  {c.title}
                </option>
              ))}
            </select>
          </label>
          <label htmlFor="assessment-file" className="block">
            Reviewed session JSON (maximum 2 MB)
            <Input
              id="assessment-file"
              type="file"
              accept=".json,application/json"
              onChange={e => setFile(e.target.files?.[0] ?? null)}
            />
          </label>
          <Button type="submit" disabled={!file || upload.isPending}>
            {upload.isPending ? "Importing…" : "Import inputs"}
          </Button>
          {upload.error && (
            <p role="alert" className="text-destructive">
              {upload.error.message}
            </p>
          )}
        </form>
      </section>
      <section className="mt-8" aria-labelledby="sessions-heading">
        <h2 id="sessions-heading" className="text-xl font-semibold">
          Your sessions
        </h2>
        {sessions.length === 0 && (
          <p className="mt-2">No sessions yet. Import reviewed inputs to begin.</p>
        )}
        <ul className="mt-3 space-y-2">
          {sessions.map(s => (
            <li key={s.id}>
              <Button
                variant="outline"
                aria-pressed={s.id === selectedId}
                onClick={() => setSelectedId(s.id)}
              >
                {s.courseTitle} — {s.title}
              </Button>
            </li>
          ))}
        </ul>
      </section>
      {selectedId && selected.isPending && (
        <output className="mt-6">Loading session inputs…</output>
      )}
      {selected.error && (
        <p role="alert" className="mt-6 text-destructive">
          {selected.error.message}
        </p>
      )}
      {inputs && (
        <section className="mt-10 space-y-8" aria-label="Session inputs">
          <header>
            <h2 className="text-2xl font-semibold">{inputs.sessionTitle}</h2>
            <p>
              {selected.data?.courseTitle} · Input format v{inputs.formatVersion} · Transcript{" "}
              {inputs.transcript.version} · Reviewed
            </p>
            {inputs.provenance === "fictional-development" && (
              <p role="note" className="mt-2 font-semibold">
                Fictional development fixture — not real student data or a model assessment.
              </p>
            )}
            <p className="mt-2 text-sm">
              This saved snapshot is read-only. Import corrected inputs as a new session; this view
              does not grade students.
            </p>
          </header>
          <section aria-labelledby="roster-heading">
            <h3 id="roster-heading" className="text-xl font-semibold">
              Roster
            </h3>
            <ul>
              {inputs.roster.map(student => {
                const count = inputs.transcript.turns.filter(
                  t => t.speaker.kind === "student" && t.speaker.studentId === student.id
                ).length;
                return (
                  <li key={student.id} className="mt-2">
                    {student.displayName} ({student.id}) —{" "}
                    {count ? `${count} reviewed contribution(s)` : "No observed contribution"}
                  </li>
                );
              })}
            </ul>
            <p className="mt-2 text-sm text-muted-foreground">
              No observed contribution describes this transcript only. It is not evidence of poor
              understanding.
            </p>
          </section>
          <section aria-labelledby="transcript-heading">
            <h3 id="transcript-heading" className="text-xl font-semibold">
              Reviewed transcript
            </h3>
            <ol className="space-y-4">
              {inputs.transcript.turns.map(turn => (
                <li key={turn.id} id={`turn-${turn.id}`} className="mt-3 rounded border p-3">
                  <p className="text-sm font-medium">
                    {turn.id} · {turn.startMs / 1000}–{turn.endMs / 1000}s ·{" "}
                    {turn.speaker.kind === "student"
                      ? rosterNames.get(turn.speaker.studentId)
                      : turn.speaker.label}
                  </p>
                  <p className="mt-1 whitespace-pre-wrap">{turn.text}</p>
                </li>
              ))}
            </ol>
          </section>
          <section aria-labelledby="rubric-heading">
            <h3 id="rubric-heading" className="text-xl font-semibold">
              {inputs.rubric.title} — version {inputs.rubric.version}
            </h3>
            <ul>
              {inputs.rubric.criteria.map(c => (
                <li key={c.id} className="mt-3">
                  <h4 className="font-semibold">
                    {c.title} ({c.id}): {c.minScore}–{c.maxScore}
                  </h4>
                  <p>{c.description}</p>
                </li>
              ))}
            </ul>
          </section>
          <section aria-labelledby="documents-heading">
            <h3 id="documents-heading" className="text-xl font-semibold">
              Authorised course passages
            </h3>
            {inputs.documents.map(document => (
              <article key={document.id} className="mt-4">
                <h4 className="font-semibold">
                  {document.title} — {document.id}, version {document.version}
                </h4>
                <p className="text-sm">Source: {document.source}</p>
                {document.passages.map(passage => (
                  <blockquote
                    key={passage.id}
                    id={`passage-${document.id}-${passage.id}`}
                    className="mt-2 border-l-2 pl-4"
                  >
                    <p className="text-sm">
                      {document.id}/{passage.id} · Page {passage.page}
                    </p>
                    <p className="whitespace-pre-wrap">{passage.text}</p>
                  </blockquote>
                ))}
              </article>
            ))}
          </section>
          {selectedId && (
            <ParticipationPanel
              key={`participation-${selectedId}`}
              sessionId={selectedId}
              inputs={inputs}
            />
          )}
          {selectedId && <EvidencePanel key={selectedId} sessionId={selectedId} inputs={inputs} />}
        </section>
      )}
    </Page>
  );
}
