import { createMiddleware, createServerFn } from "@tanstack/react-start";
import { setResponseStatus } from "@tanstack/react-start/server";
import { vi } from "vitest";

import { requireSession } from "#/features/auth/session";
import { auth } from "#/lib/auth.server";

/**
 * Shared harness for driving real server functions through the real middleware chain in
 * integration tests (`server-function-authorization`, `upload-server-fn`). The request, the
 * session, and the response status setter are mocked per test file; everything here works
 * against those mocks.
 */
export interface ServerFunction {
  __executeServer: (opts: { method: "GET" | "POST"; data: unknown }) => Promise<unknown>;
}

/** Signs the mocked session in as `user`. */
export function signIn(user: { id: string; email: string }) {
  vi.mocked(auth.api.getSession).mockResolvedValue({ user } as never);
}

export async function call(
  serverFn: ServerFunction,
  data: unknown,
  method: "GET" | "POST" = "POST"
) {
  return (await serverFn["__executeServer"]({ method, data })) as {
    result?: unknown;
    error?: unknown;
  };
}

/** The refusal the function answered with, reduced to what a caller can observe. */
export async function refusalFrom(
  serverFn: ServerFunction,
  data: unknown,
  method: "GET" | "POST" = "POST"
) {
  vi.mocked(setResponseStatus).mockClear();
  const { error } = await call(serverFn, data, method);
  if (!(error instanceof Error)) {
    throw new Error("expected a refusal Error, but the pipeline returned none");
  }

  return { status: vi.mocked(setResponseStatus).mock.calls.at(-1)?.[0], message: error.message };
}

/**
 * Runs `run` on the server side of the pipeline behind the real session guard, so its throw
 * reaches `withSession`'s status handling as a handler's would. `.handler` is required to
 * attach `__executeServer`; the terminal body never runs in the uncompiled test module (the
 * compiler supplies it in a real build).
 */
export function seam(run: () => Promise<unknown>) {
  return createServerFn({ method: "POST" })
    .middleware([requireSession])
    .middleware([
      createMiddleware({ type: "function" }).server(async ({ next }) => {
        await run();
        return next();
      }),
    ])
    .handler(() => undefined);
}
