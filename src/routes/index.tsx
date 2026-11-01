import { createFileRoute } from "@tanstack/react-router";
import { LandingPage } from "#/components/pages/landing";
import { createSeoHead, getStructuredData } from "#/lib/seo";

export const Route = createFileRoute("/")({
  head: () =>
    createSeoHead({
      title: "ClassPart AI — Classroom Discussions",
      description:
        "A foundation for classroom discussions, with secure accounts, personal notes, and file uploads.",
      path: "/",
      structuredData: getStructuredData(),
    }),
  component: LandingPage,
});
