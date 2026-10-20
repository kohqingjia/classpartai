import {
  sentryGlobalFunctionMiddleware,
  sentryGlobalRequestMiddleware,
} from "@sentry/tanstackstart-react";
import { createMiddleware, createStart } from "@tanstack/react-start";
import { logger } from "#/lib/logger";

const loggerMiddleware = createMiddleware({ type: "request" }).server(async ({ request, next }) => {
  logger.info("Incoming request", {
    method: request.method,
    url: new URL(request.url).pathname,
  });
  return next();
});

/**
 * TanStack Start instance with Sentry global middlewares and custom logging.
 *
 * - sentryGlobalRequestMiddleware: attaches request context to Sentry events.
 * - sentryGlobalFunctionMiddleware: captures errors in server functions.
 * - loggerMiddleware: logs all incoming requests for audit/metrics.
 *
 * These must be first in the arrays to ensure all errors and requests are
 * captured before any other middleware has a chance to swallow them.
 */
export const startInstance = createStart(() => {
  return {
    requestMiddleware: [sentryGlobalRequestMiddleware, loggerMiddleware],
    functionMiddleware: [sentryGlobalFunctionMiddleware],
  };
});
