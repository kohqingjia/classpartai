import { configureSync, getConsoleSink, getLogger, resetSync } from "@logtape/logtape";
import { getSentrySink } from "@logtape/sentry";

interface AppLoggingOptions {
  isDevelopment: boolean;
  enableSentrySink: boolean;
}

export const logger = getLogger(["app"]);
export function configureAppLogging({ isDevelopment, enableSentrySink }: AppLoggingOptions) {
  resetSync();

  const sinks = {
    console: getConsoleSink(),
    ...(enableSentrySink ? { sentry: getSentrySink() } : {}),
  };

  const loggerSinks = enableSentrySink ? ["console", "sentry"] : ["console"];

  configureSync({
    sinks,
    loggers: [
      {
        category: ["logtape", "meta"],
        lowestLevel: "warning",
        sinks: ["console"],
      },
      {
        category: ["app"],
        lowestLevel: isDevelopment ? "debug" : "info",
        sinks: loggerSinks,
      },
    ],
  });
}
