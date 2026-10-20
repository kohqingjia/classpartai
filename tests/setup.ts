// oxlint-disable node/no-process-env
// oxlint-disable-next-line import/no-unassigned-import
import "zod/compile";

// DATABASE_URL is deliberately not defaulted here: an integration run must use the container
// globalSetup starts, and a unit run that silently reaches a local database hides the mistake.
process.env.BETTER_AUTH_SECRET ??= "01234567890123456789012345678901";
process.env.BETTER_AUTH_URL ??= "http://localhost:3000";

if (typeof window !== "undefined" && !window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }) as MediaQueryList;
}
