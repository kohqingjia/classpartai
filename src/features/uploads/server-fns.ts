import { createServerFn } from "@tanstack/react-start";

import { requireSession } from "#/features/auth/session";
import { parseUploadRequest } from "#/features/uploads/schema";

/**
 * Routes import this module, so it stays free of any static server import — the middleware
 * pipeline is client-safe, and `./presign.server` is reached inside the handler, which TanStack
 * Start strips from the client build.
 */
export const createUploadUrl = createServerFn({ method: "POST" })
  .middleware([requireSession])
  .validator(parseUploadRequest)
  .handler(async ({ data, context }) => {
    const { handleCreateUploadUrl } = await import("#/features/uploads/presign.server");
    return handleCreateUploadUrl(data, context.user);
  });
