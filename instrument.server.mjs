import * as Sentry from "@sentry/tanstackstart-react";

const sentryDsn = process.env.VITE_SENTRY_DSN;

if (!sentryDsn) {
  console.warn("VITE_SENTRY_DSN is not defined. Sentry is disabled.");
}

if (sentryDsn) {
  Sentry.init({
    dsn: sentryDsn,
    // PII capture is off by default. Enable only after reviewing your data-handling
    // obligations — set sendDefaultPii: true when you intentionally want request
    // bodies, IP addresses, and user identifiers forwarded to Sentry.
    sendDefaultPii: false,
    // Keep server traces at 10% in production to control volume and cost.
    // Raise to 1.0 temporarily for debugging, then lower before shipping.
    tracesSampleRate: 0.1,
    replaysSessionSampleRate: 0,
    replaysOnErrorSampleRate: 1,
    enableLogs: true,
    integrations: [],
  });
}
