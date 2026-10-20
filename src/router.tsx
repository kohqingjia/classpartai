// oxlint-disable-next-line import/no-unassigned-import
import "zod/compile";
import * as Sentry from "@sentry/tanstackstart-react";
import { createRouter as createTanStackRouter } from "@tanstack/react-router";
import { setupRouterSsrQueryIntegration } from "@tanstack/react-router-ssr-query";

import { QueryClient } from "@tanstack/react-query";

import { configureAppLogging } from "./lib/logger";
import { routeTree } from "./routeTree.gen";
import { env } from "./env";

const REPLAY_SESSION_SAMPLE_RATE: number = 0.1;
const REPLAY_ERROR_SAMPLE_RATE: number = 1;

export function getRouter() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { staleTime: 30_000 } },
  });
  const context = { queryClient };

  const router = createTanStackRouter({
    routeTree,
    context,
    scrollRestoration: true,
    defaultPreload: "intent",
    defaultPreloadStaleTime: 0,
  });

  setupRouterSsrQueryIntegration({ router, queryClient: context.queryClient });

  // Initialize Sentry on the client only (not during SSR)
  if (!router.isServer) {
    const globalState = globalThis as typeof globalThis & {
      __appSentryInitialized__?: boolean;
    };

    const sentryDsn = env.VITE_SENTRY_DSN;

    if (!globalState.__appSentryInitialized__ && sentryDsn) {
      Sentry.init({
        dsn: sentryDsn,
        integrations: [Sentry.tanstackRouterBrowserTracingIntegration(router)],
        tracesSampleRate: 0.1,
        replaysSessionSampleRate: REPLAY_SESSION_SAMPLE_RATE,
        replaysOnErrorSampleRate: REPLAY_ERROR_SAMPLE_RATE,
        enableLogs: true,
        sendDefaultPii: false,
      });
      globalState.__appSentryInitialized__ = true;

      // Replay's rrweb payload is fetched from Sentry's CDN instead of shipping in the entry
      // chunk; the integration applies its own sampling, so this only gates whether it loads.
      // Tradeoff: there is no pre-error replay buffer until the CDN fetch resolves.
      if (REPLAY_SESSION_SAMPLE_RATE > 0 || REPLAY_ERROR_SAMPLE_RATE > 0) {
        void Sentry.lazyLoadIntegration("replayIntegration")
          .then(replayIntegration => Sentry.addIntegration(replayIntegration()))
          .catch(() => {
            // A blocked or failed CDN fetch must not break the app; tracing still works.
          });
      }
    }

    configureAppLogging({
      isDevelopment: import.meta.env.DEV,
      enableSentrySink: Boolean(sentryDsn),
    });
  }

  return router;
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof getRouter>;
  }
}
