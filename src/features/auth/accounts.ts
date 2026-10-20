import { createServerFn } from "@tanstack/react-start";
import { queryOptions } from "@tanstack/react-query";

import { requireSession } from "#/features/auth/session";

export const listAccounts = createServerFn({ method: "GET" })
  .middleware([requireSession])
  .handler(async () => {
    const [{ getRequest }, { auth }] = await Promise.all([
      import("@tanstack/react-start/server"),
      import("#/lib/auth.server"),
    ]);

    return auth.api.listUserAccounts({ headers: getRequest().headers });
  });

export function accountOptions(userId: string) {
  return queryOptions({
    // userId only scopes the cache key — the server derives the list from the session.
    queryKey: ["auth", "accounts", userId],
    queryFn: () => listAccounts(),
    retry: false,
  });
}
