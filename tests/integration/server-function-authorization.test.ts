// oxlint-disable node/no-process-env
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { drizzle } from "drizzle-orm/node-postgres";
import { Pool } from "pg";

import * as schema from "#/db/schema";
import { listAccounts } from "#/features/auth/accounts";
import { getCurrentUser } from "#/features/auth/session";
import { handleDeleteNote } from "#/features/notes/records.server";
import { createNote, deleteNote, listNotes } from "#/features/notes/server-fns";
import { auth } from "#/lib/auth.server";
import { call, refusalFrom, seam, signIn } from "./server-fn-harness";

/**
 * The server-function boundary: `__executeServer` is the entry the HTTP route calls, so each
 * case below runs the real function's own middleware chain — not a reconstruction of it — and
 * can catch a function wired to the wrong guard. The request, the session, and the response
 * status setter are the three things the runtime supplies, so they are the three things mocked.
 *
 * On a refusal the middleware short-circuits: `error` is the thrown `Error` an in-app caller
 * catches, and `setResponseStatus` carries the HTTP status a direct caller sees. The handler
 * below it never runs (the uncompiled test module does not carry a handler body — TanStack
 * Start's compiler supplies it in a real build, which the e2e suite exercises end to end).
 */
const currentRequest = new Request("http://localhost:3000/_serverFn", { method: "POST" });

vi.mock("@tanstack/react-start/server", () => ({
  getRequest: () => currentRequest,
  setResponseStatus: vi.fn<(code: number) => void>(),
}));

vi.mock("#/lib/auth.server", () => ({
  auth: { api: { getSession: vi.fn<() => Promise<unknown>>() } },
}));

/**
 * TanStack Start's async-local context is what a live server request provides and what the
 * middleware runner reads start options from. Supplying an empty one is what lets the real
 * server-side entry point run outside a request.
 */
vi.mock("@tanstack/start-storage-context", () => ({
  getStartContext: () => ({ startOptions: {}, contextAfterGlobalMiddlewares: {} }),
}));

const authzUser = { id: "usr_authz", email: "authz@example.com" };

describe("server-function authorization", () => {
  describe("notes", () => {
    const endpoints = [
      { fn: listNotes, data: undefined, method: "GET" as const },
      { fn: createNote, data: { title: "A note" }, method: "POST" as const },
      { fn: deleteNote, data: { id: 1 }, method: "POST" as const },
    ];

    it("requires a session for every notes endpoint", async () => {
      vi.mocked(auth.api.getSession).mockResolvedValue(null);

      // The shared mocked request context keeps its lazy module loading sequential.
      for (const endpoint of endpoints) {
        // oxlint-disable-next-line no-await-in-loop
        expect(await refusalFrom(endpoint.fn, endpoint.data, endpoint.method)).toEqual({
          status: 401,
          message: "Unauthorized",
        });
      }
    });

    it("refuses the session before the payload is even validated", async () => {
      vi.mocked(auth.api.getSession).mockResolvedValue(null);

      expect(await refusalFrom(createNote, { title: "" })).toEqual({
        status: 401,
        message: "Unauthorized",
      });
    });

    it("lets a signed-in user through to the rest of the chain", async () => {
      signIn(authzUser);

      expect((await call(listNotes, undefined, "GET")).error).toBeUndefined();
      expect((await call(createNote, { title: "A note" })).error).toBeUndefined();
      expect((await call(deleteNote, { id: 1 })).error).toBeUndefined();
    });
  });

  describe("accounts", () => {
    it("answers 401 to an unauthenticated settings load", async () => {
      vi.mocked(auth.api.getSession).mockResolvedValue(null);

      expect(await refusalFrom(listAccounts, undefined, "GET")).toEqual({
        status: 401,
        message: "Unauthorized",
      });
    });

    it("lets a signed-in user through", async () => {
      signIn(authzUser);

      expect((await call(listAccounts, undefined, "GET")).error).toBeUndefined();
    });

    // `getCurrentUser` is intentionally session-optional (every route reads it to tell a
    // signed-out visitor they are signed out), so "no session" is the allow path, not a 401.
    it("answers the current user with no session, so a rewire to requireSession would fail", async () => {
      vi.mocked(auth.api.getSession).mockResolvedValue(null);

      expect((await call(getCurrentUser, undefined, "GET")).error).toBeUndefined();
    });
  });

  /**
   * The matrix above proves each endpoint refuses at the middleware boundary, and the handler
   * tests prove each handler throws the right error class. Neither executes the join —
   * `withSession`'s catch that sets the HTTP status for the error the caller catches.
   *
   * The uncompiled test module carries no handler body (see the file comment), so the case calls
   * a real handler from a middleware placed after the real session guard. The handler's throw
   * then travels the same `next()` path a terminal handler's would, into `withSession`.
   */
  describe("refusal seam", () => {
    let pool: Pool;
    let database: ReturnType<typeof drizzle<typeof schema>>;

    beforeAll(() => {
      pool = new Pool({ connectionString: process.env.DATABASE_URL });
      database = drizzle(pool, { schema });
    });

    afterAll(async () => {
      await pool.end();
    });

    it("turns a handler's NotFoundError into the 404 a direct caller receives", async () => {
      signIn(authzUser);

      const refused = await refusalFrom(
        seam(() =>
          handleDeleteNote(
            { id: 2_147_483_647 },
            { id: "usr_authz", email: "x@y.z" },
            database as never
          )
        ),
        {}
      );

      expect(refused).toEqual({ status: 404, message: "Note not found" });
    });

    it("refuses before the guarded work runs, and lets a signed-in user run it", async () => {
      const guardedWork = vi.fn<() => void>();
      const probe = seam(async () => {
        guardedWork();
      });

      vi.mocked(auth.api.getSession).mockResolvedValue(null);
      expect(await refusalFrom(probe, {})).toEqual({ status: 401, message: "Unauthorized" });
      expect(guardedWork).not.toHaveBeenCalled();

      signIn(authzUser);
      expect((await call(probe, {})).error).toBeUndefined();
      expect(guardedWork).toHaveBeenCalledTimes(1);
    });
  });

  /**
   * With the session guard satisfied, the validator the server function declares runs on the
   * server side of the same pipeline. The handler body stays out of a Vitest build (see the file
   * comment), but the schema is part of the boundary and its refusal is observable here.
   */
  describe("validation at the server-function boundary", () => {
    it("refuses a malformed title with a 400 and the schema's own message", async () => {
      signIn(authzUser);

      expect(await refusalFrom(createNote, { title: "   " })).toEqual({
        status: 400,
        message: "Title is required",
      });
      expect(await refusalFrom(createNote, { title: "a".repeat(256) })).toEqual({
        status: 400,
        message: "Title must be 255 characters or fewer",
      });
    });
  });
});
