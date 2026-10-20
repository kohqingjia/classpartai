import { z } from "zod";

import { ValidationError } from "#/features/auth/session";

export const UploadRequestSchema = z.object({
  filename: z.string().min(1),
  contentType: z.string().min(1),
  size: z.number().nonnegative(),
});

// Zod's own message is a JSON dump of every issue; callers surface `err.message` straight at the
// user, so the server function's validator goes through this and rethrows one sentence.
export function parseUploadRequest(data: unknown) {
  const parsed = UploadRequestSchema.safeParse(data);
  if (!parsed.success) throw new ValidationError(parsed.error.issues[0].message);
  return parsed.data;
}
