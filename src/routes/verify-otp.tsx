import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";
import { VerifyOtpPage } from "#/features/auth/components/verify-otp-page";
import { createSeoHead } from "#/lib/seo";

export const Route = createFileRoute("/verify-otp")({
  validateSearch: z.object({
    email: z.email(),
    flow: z.enum(["sign-in", "sign-up"]),
  }),
  head: () =>
    createSeoHead({
      title: "Verify Code — ClassPart AI",
      noindex: true,
    }),
  component: VerifyOtpPage,
});
