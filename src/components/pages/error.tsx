import * as Sentry from "@sentry/tanstackstart-react";
import * as React from "react";
import { Link } from "@tanstack/react-router";
import type { ErrorComponentProps } from "@tanstack/react-router";

import { cn } from "cn";
import { Button } from "#/components/ui/button";
import { Page } from "#/components/custom/page";
import { RootDocument } from "#/components/layout/root-document";

interface ErrorPageProps {
  error: unknown;
  reset?: () => void;
  className?: string;
  title?: string;
}

export function ErrorPage({
  error,
  reset,
  className,
  title = "Something went wrong",
}: ErrorPageProps) {
  const message = error instanceof Error ? error.message : String(error);

  return (
    <Page
      className={cn("flex min-h-[70vh] max-w-md flex-col items-center justify-center", className)}
    >
      <div className="w-full space-y-8 animate-in fade-in duration-500">
        <div className="space-y-3">
          <p className="font-mono text-xs tracking-caps text-muted-foreground uppercase">Error</p>
          <h1 className="font-heading text-2xl font-semibold tracking-tight md:text-3xl">
            {title}
          </h1>
        </div>

        <pre className="max-h-48 overflow-auto rounded-md border border-border bg-card p-4 font-mono text-xs break-words whitespace-pre-wrap text-muted-foreground">
          {message}
        </pre>

        <div className="flex flex-col items-start gap-3">
          {reset && (
            <Button type="button" variant="link" size="sm" onClick={reset}>
              Try again
            </Button>
          )}
          <Button variant="link" size="sm" render={<Link to="/" />}>
            Back to home
          </Button>
        </div>
      </div>
    </Page>
  );
}

/**
 * The root route's error boundary. A boundary replaces everything beneath `<html>`, so it
 * re-renders the document shell itself, and it is the one place that reports the failure to
 * Sentry — on the server during SSR, and again on the client once it hydrates.
 */
export function RootErrorPage(props: ErrorComponentProps) {
  // Capture SSR rendering exceptions manually as per documentation
  if (typeof window === "undefined") {
    Sentry.captureException(props.error);
  }

  React.useEffect(() => {
    Sentry.captureException(props.error);
  }, [props.error]);

  return (
    <RootDocument meta={<meta name="robots" content="noindex, nofollow" />}>
      <ErrorPage error={props.error} reset={props.reset} />
    </RootDocument>
  );
}

/** The root route's 404. Nothing to report — the address simply matched no route. */
export function RootNotFoundPage() {
  return (
    <RootDocument meta={<meta name="robots" content="noindex, nofollow" />}>
      <ErrorPage error="The page you are looking for does not exist." title="404 - Not Found" />
    </RootDocument>
  );
}
