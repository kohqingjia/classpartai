import { createFileRoute } from "@tanstack/react-router";
import { logger } from "#/lib/logger";

export const Route = createFileRoute("/api/sentry-example")({
  server: {
    handlers: {
      GET: async () => {
        if (import.meta.env.PROD) {
          return new Response(null, { status: 404 });
        }

        logger.error("Triggering Sentry Example Route Error...", {
          time: new Date().toISOString(),
        });
        throw new Error("Sentry Example Route Error");
      },
    },
  },
});
