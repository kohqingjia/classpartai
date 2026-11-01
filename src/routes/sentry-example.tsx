import { createFileRoute, notFound } from "@tanstack/react-router";
import { SentryExamplePage } from "#/components/pages/sentry-example";
import { createSeoHead } from "#/lib/seo";

export const Route = createFileRoute("/sentry-example")({
  beforeLoad: () => {
    if (import.meta.env.PROD) {
      throw notFound();
    }
  },
  head: () =>
    createSeoHead({
      title: "Sentry Test — ClassPart AI",
      noindex: true,
    }),
  component: SentryExamplePage,
});
