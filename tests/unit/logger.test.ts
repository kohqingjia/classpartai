import { configureAppLogging } from "#/lib/logger";
import { beforeEach, describe, expect, test, vi } from "vitest";

const { mockConfigureSync, mockResetSync, mockGetConsoleSink, mockGetLogger, mockGetSentrySink } =
  vi.hoisted(() => ({
    mockConfigureSync: vi.fn<() => void>(),
    mockResetSync: vi.fn<() => void>(),
    mockGetConsoleSink: vi.fn<() => unknown>(),
    mockGetLogger: vi.fn<() => Record<string, unknown>>(() => ({})),
    mockGetSentrySink: vi.fn<() => unknown>(),
  }));

vi.mock("@logtape/logtape", () => ({
  configureSync: mockConfigureSync,
  resetSync: mockResetSync,
  getConsoleSink: mockGetConsoleSink,
  getLogger: mockGetLogger,
}));

vi.mock("@logtape/sentry", () => ({
  getSentrySink: mockGetSentrySink,
}));

describe("configureAppLogging", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetConsoleSink.mockReturnValue("consoleSink");
    mockGetSentrySink.mockReturnValue("sentrySink");
  });

  test("dev + no sentry: console sink, debug level", () => {
    configureAppLogging({ isDevelopment: true, enableSentrySink: false });

    expect(mockResetSync).toHaveBeenCalledOnce();
    expect(mockGetSentrySink).not.toHaveBeenCalled();
    expect(mockConfigureSync).toHaveBeenCalledWith({
      sinks: { console: "consoleSink" },
      loggers: [
        { category: ["logtape", "meta"], lowestLevel: "warning", sinks: ["console"] },
        { category: ["app"], lowestLevel: "debug", sinks: ["console"] },
      ],
    });
  });

  test("dev + sentry: console+sentry sinks, debug level", () => {
    configureAppLogging({ isDevelopment: true, enableSentrySink: true });

    expect(mockGetSentrySink).toHaveBeenCalledOnce();
    expect(mockConfigureSync).toHaveBeenCalledWith({
      sinks: { console: "consoleSink", sentry: "sentrySink" },
      loggers: [
        { category: ["logtape", "meta"], lowestLevel: "warning", sinks: ["console"] },
        { category: ["app"], lowestLevel: "debug", sinks: ["console", "sentry"] },
      ],
    });
  });

  test("prod + no sentry: console sink, info level", () => {
    configureAppLogging({ isDevelopment: false, enableSentrySink: false });

    expect(mockGetSentrySink).not.toHaveBeenCalled();
    expect(mockConfigureSync).toHaveBeenCalledWith({
      sinks: { console: "consoleSink" },
      loggers: [
        { category: ["logtape", "meta"], lowestLevel: "warning", sinks: ["console"] },
        { category: ["app"], lowestLevel: "info", sinks: ["console"] },
      ],
    });
  });

  test("prod + sentry: console and sentry sinks, info level", () => {
    configureAppLogging({ isDevelopment: false, enableSentrySink: true });

    expect(mockGetSentrySink).toHaveBeenCalledOnce();
    expect(mockConfigureSync).toHaveBeenCalledWith({
      sinks: { console: "consoleSink", sentry: "sentrySink" },
      loggers: [
        { category: ["logtape", "meta"], lowestLevel: "warning", sinks: ["console"] },
        { category: ["app"], lowestLevel: "info", sinks: ["console", "sentry"] },
      ],
    });
  });
});
