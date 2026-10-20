import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";
import { ResetPasswordPage } from "#/features/auth/components/reset-password-page";
import { createSeoHead } from "#/lib/seo";

export const Route = createFileRoute("/reset-password")({
  validateSearch: z.object({
    token: z.string().optional(),
    error: z.string().optional(),
  }),
  head: () =>
    createSeoHead({
      title: "Reset Password — TanStack Start Template",
      noindex: true,
    }),
  component: ResetPasswordPage,
});
