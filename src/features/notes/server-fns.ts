import { createServerFn } from "@tanstack/react-start";

import { requireSession } from "#/features/auth/session";
import { parseCreateNote, parseDeleteNote } from "#/features/notes/schema";

/**
 * Routes import this module, so it stays free of any static server import — the middleware
 * pipeline is client-safe, and `./records.server` and `#/db` are reached inside the handlers,
 * which TanStack Start strips from the client build.
 */
async function loadServer() {
  return Promise.all([import("#/db"), import("#/features/notes/records.server")]);
}

export const listNotes = createServerFn({ method: "GET" })
  .middleware([requireSession])
  .handler(async ({ context }) => {
    const [{ db }, { handleListNotes }] = await loadServer();
    return handleListNotes(context.user, db);
  });

export const createNote = createServerFn({ method: "POST" })
  .middleware([requireSession])
  .validator(parseCreateNote)
  .handler(async ({ data, context }) => {
    const [{ db }, { handleCreateNote }] = await loadServer();
    return handleCreateNote(data, context.user, db);
  });

export const deleteNote = createServerFn({ method: "POST" })
  .middleware([requireSession])
  .validator(parseDeleteNote)
  .handler(async ({ data, context }) => {
    const [{ db }, { handleDeleteNote }] = await loadServer();
    return handleDeleteNote(data, context.user, db);
  });
