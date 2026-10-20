import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/_authenticated")({
  /**
   * `__root.tsx` resolved the session for this navigation already, so the boundary is just the
   * refusal now. The re-emit narrows `SessionUser | null` to `SessionUser`: every route beneath
   * this one reads `context.user` and never repeats the check.
   */
  beforeLoad: ({ context }) => {
    if (!context.user) {
      throw redirect({ to: "/login" });
    }

    return { user: context.user };
  },
});
