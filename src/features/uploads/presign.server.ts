import { env } from "#/env";
import { logger } from "#/lib/logger";
import { getStorageClient, safeExtension, validateUploadRequest } from "#/lib/storage.server";
import type { UploadRequest } from "#/lib/storage.server";
import { ServiceUnavailableError, UnprocessableEntityError } from "#/features/auth/session";
import type { SessionUser } from "#/features/auth/session";

/**
 * Server-only on purpose, and named for it: `#/lib/storage.server` reaches `bun`, which would ship
 * a server runtime to the browser from any module a route can reach. `server-fns.ts` reaches this
 * through a dynamic `import()` inside `.handler()`.
 *
 * The handler is pure request/response work: the server function's middleware pipeline has already
 * resolved the session before it runs.
 */
export async function handleCreateUploadUrl(
  data: UploadRequest,
  user: SessionUser
): Promise<{ url: string; key: string }> {
  const validationError = validateUploadRequest(data);
  if (validationError) {
    throw new UnprocessableEntityError(validationError);
  }

  const client = getStorageClient(
    env.MINIO_ENDPOINT,
    env.MINIO_ACCESS_KEY,
    env.MINIO_SECRET_KEY,
    env.MINIO_BUCKET
  );
  if (!client) {
    throw new ServiceUnavailableError(
      "Storage is not configured. Set MINIO_ENDPOINT to enable uploads."
    );
  }

  const key = `uploads/${user.id}/${crypto.randomUUID()}.${safeExtension(data.contentType)}`;
  const url = client.presign(key, { method: "PUT", expiresIn: 300, type: data.contentType });

  logger.info("Generated presigned upload URL", {
    userId: user.id,
    key,
    contentType: data.contentType,
  });

  return { url, key };
}
