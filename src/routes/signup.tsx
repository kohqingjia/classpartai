import { createFileRoute, redirect } from "@tanstack/react-router";
import { SignupPage } from "#/features/auth/components/signup-page";
import { createSeoHead } from "#/lib/seo";

export const Route = createFileRoute("/signup")({
  // Allow the form to refresh session context before it navigates to the workspace.
  beforeLoad: ({ context, cause }) => {
    if (cause === "enter" && context.user) {
      throw redirect({ to: "/dashboard" });
    }
  },
  head: () =>
    createSeoHead({
      title: "Sign Up — ClassPart AI",
      noindex: true,
    }),
  component: SignupPage,
});
