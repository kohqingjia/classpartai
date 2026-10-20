import { Suspense } from "react";
import { createRootRouteWithContext, Outlet } from "@tanstack/react-router";
import type { QueryClient } from "@tanstack/react-query";

import { Devtools } from "#/components/devtools";
import { Header } from "#/components/layout/header";
import { RootDocument } from "#/components/layout/root-document";
import { RootErrorPage, RootNotFoundPage } from "#/components/pages/error";
import { getCurrentUser } from "#/features/auth/session";
import { logger } from "#/lib/logger";
// oxlint-disable-next-line import/no-unassigned-import
import "../globals.css";

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  // The one place the session is resolved, once per navigation, for every route — `_authenticated`
  // narrows what lands here rather than fetching it again. The header reads it from context, so
  // the signed-in nav is part of the SSR markup instead of appearing a moment after hydration.
  // A failed lookup degrades to a signed-out nav rather than taking public routes down with it;
  // `_authenticated` still refuses protected routes.
  beforeLoad: async () => {
    try {
      return { user: await getCurrentUser() };
    } catch (error) {
      logger.error("Session lookup failed; rendering signed-out", { error });
      return { user: null };
    }
  },
  head: () => ({
    meta: [
      {
        charSet: "utf-8",
      },
      {
        name: "viewport",
        content: "width=device-width, initial-scale=1",
      },
      {
        name: "theme-color",
        content: "#09090b",
      },
      {
        name: "color-scheme",
        content: "light dark",
      },
      {
        title: "TanStack Start Template",
      },
    ],
    links: [
      { rel: "icon", href: "/favicon.ico", sizes: "any" },
      { rel: "icon", href: "/favicon.svg", type: "image/svg+xml" },
      { rel: "apple-touch-icon", href: "/apple-touch-icon.png" },
      { rel: "manifest", href: "/site.webmanifest" },
    ],
  }),
  component: () => (
    <RootDocument>
      <Header />
      <Outlet />
      {import.meta.env.DEV && (
        <Suspense fallback={null}>
          <Devtools />
        </Suspense>
      )}
    </RootDocument>
  ),
  errorComponent: RootErrorPage,
  notFoundComponent: RootNotFoundPage,
});
