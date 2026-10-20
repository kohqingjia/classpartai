import { describe, expect, it, vi } from "vitest";

import { createUploadUrl } from "#/features/uploads/server-fns";
import { handleCreateUploadUrl } from "#/features/uploads/presign.server";
import { auth } from "#/lib/auth.server";
import * as storage from "#/lib/storage.server";
import { call, refusalFrom, seam, signIn } from "./server-fn-harness";

/**
 * The upload server-function boundary: `__executeServer` is the entry the HTTP route calls, so the
 * cases below run the real function's own middleware chain. The request, the session, and the
 * response status setter are the three things the runtime supplies, so they are the three things
 * mocked here.
 *
 * The uncompiled test module carries no `.handler()` body (TanStack Start's compiler supplies it in
 * a real build, as `server-function-authorization.test.ts` explains), so the request/response
 * handler's own refusals are exercised through the shared seam: a real middleware placed after the
 * real session guard calls `handleCreateUploadUrl`, and its throw travels the same `next()` path
 * into `withSession`'s status handling.
 */
const currentRequest = new Request("http://localhost:3000/_serverFn", { method: "POST" });

vi.mock("@tanstack/react-start/server", () => ({
  getRequest: () => currentRequest,
  setResponseStatus: vi.fn<(code: number) => void>(),
}));

vi.mock("#/lib/auth.server", () => ({
  auth: { api: { getSession: vi.fn<() => Promise<unknown>>() } },
}));

vi.mock("@tanstack/start-storage-context", () => ({
  getStartContext: () => ({ startOptions: {}, contextAfterGlobalMiddlewares: {} }),
}));

vi.mock("#/lib/storage.server", async importOriginal => {
  const original = await importOriginal<typeof storage>();
  return { ...original };
});

vi.mock("#/env", () => ({
  env: {
    MINIO_ENDPOINT: "http://localhost:9000",
    MINIO_ACCESS_KEY: "minioadmin",
    MINIO_SECRET_KEY: "minioadmin",
    MINIO_BUCKET: "test-bucket",
  },
}));

const user = { id: "usr_upload", email: "upload@example.com" };
const validRequest = { filename: "photo.jpg", contentType: "image/jpeg", size: 2048 };

describe("createUploadUrl server function", () => {
  it("answers 401 to a caller with no session", async () => {
    vi.mocked(auth.api.getSession).mockResolvedValue(null);

    expect(await refusalFrom(createUploadUrl, validRequest)).toEqual({
      status: 401,
      message: "Unauthorized",
    });
  });

  it("refuses a malformed body with a 400 and the schema's own message", async () => {
    signIn(user);

    const refused = await refusalFrom(createUploadUrl, {});
    expect(refused.status).toBe(400);
    expect(refused.message).toMatch(/expected string/i);
  });

  it("answers 422 when the file type is not allowed", async () => {
    signIn(user);

    expect(
      await refusalFrom(
        seam(() =>
          handleCreateUploadUrl(
            { filename: "malicious.exe", contentType: "application/x-msdownload", size: 1024 },
            user
          )
        ),
        {}
      )
    ).toEqual({ status: 422, message: "Unsupported file type" });
  });

  it("answers 503 when storage is not configured", async () => {
    signIn(user);
    vi.spyOn(storage, "getStorageClient").mockReturnValue(null);

    expect(
      await refusalFrom(
        seam(() => handleCreateUploadUrl(validRequest, user)),
        {}
      )
    ).toEqual({
      status: 503,
      message: "Storage is not configured. Set MINIO_ENDPOINT to enable uploads.",
    });
  });

  it("returns a presigned URL and key when storage accepts the request", async () => {
    signIn(user);
    const presign = vi.fn<() => string>().mockReturnValue("http://minio.local/upload");
    vi.spyOn(storage, "getStorageClient").mockReturnValue({ presign } as never);

    const result = await handleCreateUploadUrl(validRequest, user);
    expect(result.url).toBe("http://minio.local/upload");
    expect(result.key).toMatch(/^uploads\/usr_upload\/[0-9a-f-]+\.jpg$/);
    expect(presign).toHaveBeenCalledWith(result.key, {
      method: "PUT",
      expiresIn: 300,
      type: "image/jpeg",
    });
  });

  it("lets a signed-in user through to the rest of the chain", async () => {
    signIn(user);

    expect(
      (
        await call(
          seam(() => handleCreateUploadUrl(validRequest, user)),
          {}
        )
      ).error
    ).toBeUndefined();
  });
});
