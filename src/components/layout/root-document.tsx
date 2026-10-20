import { HeadContent, Scripts } from "@tanstack/react-router";
import { useEffect } from "react";
import type { ReactNode } from "react";

import { ThemeProvider } from "#/components/providers/theme-provider";
import { Toaster } from "#/components/ui/sonner";

/**
 * The HTML document every render is wrapped in — the root route's shell and the one the error
 * and not-found boundaries reuse, since a boundary replaces the whole tree beneath `<html>`.
 * It lives beside the header rather than in `src/routes/__root.tsx`, which keeps that file to
 * routing.
 */
export function RootDocument({ children, meta }: { children: ReactNode; meta?: ReactNode }) {
  // Runs only after React attaches, never during SSR, so E2E specs can wait on a real hydration
  // signal (`body[data-hydrated]`) instead of network silence, which can settle before handlers
  // are live under the dev server's on-demand transforms.
  useEffect(() => {
    document.body.dataset.hydrated = "true";
  }, []);

  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <HeadContent />
        {meta}
      </head>
      <body>
        <ThemeProvider defaultTheme="light" storageKey="template-theme">
          {children}
        </ThemeProvider>
        <Scripts />
        <Toaster richColors />
      </body>
    </html>
  );
}
