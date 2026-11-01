import type { AssessmentInputs } from "#/features/assessments/schema";
import type { Proposal } from "#/features/participation/schema";

/** Fictional, manually authored unassessed draft for automated review/transport checks.
 * This is neither model output nor a human-labelled scoring evaluation. */
export function fictionalProposal(inputs: AssessmentInputs): Proposal {
  return {
    findings: inputs.roster.flatMap(s =>
      inputs.rubric.criteria.map(c => ({
        studentId: s.id,
        criterionId: c.id,
        status: "insufficient_evidence" as const,
        score: null,
        turnIds: [],
        citations: [],
        justification: "Fictional test draft: professor evidence review is pending",
        limitations: ["Not a model assessment"],
      }))
    ),
    feedback: inputs.roster.map(s => ({
      studentId: s.id,
      strengths:
        s.id === "student-c"
          ? "No observed contribution in this reviewed discussion; understanding remains unassessed."
          : "Your attributed contribution provides material for professor review.",
      nextStep: "At the next discussion, explain one claim with an example and invite a response.",
      limitations: ["Fictional manual draft; no ability inference or model evaluation"],
      turnIds: [],
      citations: [],
      goalIds: [],
    })),
  };
}
