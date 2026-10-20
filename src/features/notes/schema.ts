import { z } from "zod";

import { ValidationError } from "#/features/auth/session";

export const CreateNoteInput = z.object({
  title: z
    .string()
    .trim()
    .min(1, "Title is required")
    .max(255, "Title must be 255 characters or fewer"),
});

export const DeleteNoteInput = z.object({ id: z.number() });

// Zod's own message is a JSON dump of every issue; routes toast `err.message` straight at
// the user, so both entry points go through this and surface one sentence.
export function parseCreateNote(data: unknown) {
  const parsed = CreateNoteInput.safeParse(data);
  if (!parsed.success) throw new ValidationError(parsed.error.issues[0].message);
  return parsed.data;
}

export function parseDeleteNote(data: unknown) {
  const parsed = DeleteNoteInput.safeParse(data);
  if (!parsed.success) throw new ValidationError(parsed.error.issues[0].message);
  return parsed.data;
}
