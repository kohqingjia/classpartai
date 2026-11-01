import { Link } from "@tanstack/react-router";
import { Page } from "#/components/custom/page";
import { buttonVariants } from "#/components/ui/button";

const WORKFLOW = [
  {
    title: "Prepare your class",
    description: "Bring together a participant roster and the course readings for your discussion.",
  },
  {
    title: "Capture the discussion",
    description:
      "Record a session with willing participants and keep the context for each contribution.",
  },
  {
    title: "Reflect across sessions",
    description: "Review how ideas develop and connect the conversation back to course material.",
  },
];

export function LandingPage() {
  return (
    <Page
      eyebrow="For professors"
      title="Make every discussion count."
      description="ClassPart AI is taking shape as a workspace for classroom discussions, course material, and participation over time."
    >
      <div className="mt-8 flex flex-wrap gap-4">
        <Link to="/dashboard" className={buttonVariants({ size: "lg" })}>
          Open workspace
        </Link>
        <Link to="/signup" className={buttonVariants({ variant: "outline", size: "lg" })}>
          Create account
        </Link>
      </div>
      <section className="mt-16 border-t border-border pt-8" aria-labelledby="workflow-heading">
        <h2 id="workflow-heading" className="font-heading text-2xl font-semibold tracking-tight">
          A place for your class discussions
        </h2>
        <div className="mt-8 grid gap-8 sm:grid-cols-3">
          {WORKFLOW.map((step, index) => (
            <article key={step.title}>
              <p className="font-mono text-xs text-muted-foreground">0{index + 1}</p>
              <h3 className="mt-3 font-heading text-lg font-semibold">{step.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                {step.description}
              </p>
            </article>
          ))}
        </div>
      </section>
      <aside
        className="mt-12 rounded-md border border-border bg-card p-6"
        aria-label="Development status"
      >
        <h2 className="font-heading font-semibold">Early development</h2>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          Accounts, personal notes, and file uploads are available in the workspace. Class
          management, transcription, and AI analysis are planned.
        </p>
      </aside>
    </Page>
  );
}
