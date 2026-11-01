import { createFileRoute } from "@tanstack/react-router";
import { AssessmentsPage } from "#/features/assessments/components/page";
import { listAssessmentSessions } from "#/features/assessments/server-fns";
import { createSeoHead } from "#/lib/seo";

export const Route = createFileRoute("/_authenticated/assessments")({
  loader: async () => ({ sessions: await listAssessmentSessions() }),
  head: () => createSeoHead({ title: "Assessment inputs — ClassPart AI", noindex: true }),
  component: AssessmentsPage,
});
