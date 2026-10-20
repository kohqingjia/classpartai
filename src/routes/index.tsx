import { createFileRoute } from "@tanstack/react-router";
import { LandingPage } from "#/components/pages/landing";
import { createSeoHead, getStructuredData } from "#/lib/seo";

export const Route = createFileRoute("/")({
  head: () =>
    createSeoHead({
      title: "TanStack Start Template — Production-Ready Full-Stack React",
      description:
        "Full-stack React template with TanStack Start, Nitro, React 19, Better Auth, Drizzle ORM, and Tailwind CSS v4.",
      path: "/",
      structuredData: getStructuredData(),
    }),
  component: LandingPage,
});
