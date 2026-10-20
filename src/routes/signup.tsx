import { createFileRoute, redirect } from "@tanstack/react-router";
import { SignupPage } from "#/features/auth/components/signup-page";
import { createSeoHead } from "#/lib/seo";

export const Route = createFileRoute("/signup")({
  /**
   * The session `__root.tsx` already resolved, so asking the server again would spend a second
   * roundtrip on the same navigation.
   *
   * Only an arrival is turned away. Signing up creates the session without leaving this route,
   * and the form re-resolves the context in place so the header picks the user up; that lands
   * here as `cause: "stay"` and must not bounce the visitor off the "Check your email" panel
   * they were just shown.
   */
  beforeLoad: ({ context, cause }) => {
    if (cause === "enter" && context.user) {
      throw redirect({ to: "/dashboard" });
    }
  },
  head: () =>
    createSeoHead({
      title: "Sign Up — TanStack Start Template",
      noindex: true,
    }),
  component: SignupPage,
});
