import { createFileRoute, redirect } from "@tanstack/react-router";
import { LoginPage } from "#/features/auth/components/login-page";
import { createSeoHead } from "#/lib/seo";

export const Route = createFileRoute("/login")({
  beforeLoad: ({ context }) => {
    if (context.user) {
      throw redirect({ to: "/dashboard" });
    }
  },
  head: () =>
    createSeoHead({
      title: "Sign In — ClassPart AI",
      noindex: true,
    }),
  component: LoginPage,
});
