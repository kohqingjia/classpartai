import { useEffect } from "react";
import { Page } from "#/components/custom/page";
import { Button } from "#/components/ui/button";
import { logger } from "#/lib/logger";

function handleClick() {
  const time = new Date().toISOString();
  logger.info("Button clicked", { time });
}

export function SentryExamplePage() {
  useEffect(() => {
    const time = new Date().toISOString();
    logger.info("Mounted sentry test route", { time });
  }, []);

  return (
    <Page className="flex min-h-[calc(100vh-4rem)] items-center justify-center p-4">
      <div className="w-full max-w-md space-y-4 rounded-md border border-border p-6">
        <div className="space-y-2">
          <h1 className="font-heading text-2xl font-semibold tracking-tight">Sentry client test</h1>
          <p className="text-sm text-muted-foreground">
            Open this page, then click the button and watch for a client log.
          </p>
        </div>

        <Button type="button" onClick={handleClick}>
          Log client event
        </Button>
      </div>
    </Page>
  );
}
