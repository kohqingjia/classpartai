import { createFileRoute } from "@tanstack/react-router";
import { DashboardPage, DashboardPageSkeleton } from "#/features/dashboard/components/page";
import { listNotes } from "#/features/notes/server-fns";
import { createSeoHead } from "#/lib/seo";

export const Route = createFileRoute("/_authenticated/dashboard")({
  loader: async () => {
    const notes = await listNotes();
    return { notes };
  },
  head: () =>
    createSeoHead({
      title: "Dashboard — ClassPart AI",
      noindex: true,
    }),
  pendingComponent: DashboardPageSkeleton,
  component: DashboardPage,
});
