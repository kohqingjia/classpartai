import { betterAuth } from "better-auth";
import { drizzleAdapter } from "better-auth/adapters/drizzle";
import { tanstackStartCookies } from "better-auth/tanstack-start";
import { emailOTP } from "better-auth/plugins";
import { passkey } from "@better-auth/passkey";
import { createElement } from "react";

import { db } from "#/db";
import * as schema from "#/db/schema";
import { env } from "#/env";
import { sendEmail } from "#/lib/mailer.server";
import { OtpEmail } from "#/features/emails/components/otp-email";
import { ResetPasswordEmail } from "#/features/emails/components/reset-password-email";
import { VerificationEmail } from "#/features/emails/components/verification-email";
import { logger } from "#/lib/logger";

export const auth = betterAuth({
  database: drizzleAdapter(db, {
    provider: "pg",
    schema,
  }),
  secret: env.BETTER_AUTH_SECRET,
  baseURL: env.BETTER_AUTH_URL,

  // Password sign-ups start unverified, and an email-OTP sign-in by an unverified user makes
  // Better Auth revoke every account it holds (its account-takeover defence) — which would drop
  // the password the user just set. Sending a verification link on sign-up closes that window.
  emailVerification: {
    sendOnSignUp: true,
    async sendVerificationEmail({ user, url }) {
      logger.info("Sending verification email", { email: user.email });
      await sendEmail(user.email, "Verify your email", createElement(VerificationEmail, { url }));
    },
  },

  emailAndPassword: {
    enabled: true,
    async sendResetPassword({ user, url }) {
      logger.info("Sending password reset email", { email: user.email });
      await sendEmail(
        user.email,
        "Reset your password",
        createElement(ResetPasswordEmail, { url, user: { email: user.email } })
      );
    },
  },

  socialProviders:
    env.GOOGLE_CLIENT_ID && env.GOOGLE_CLIENT_SECRET
      ? {
          google: {
            prompt: "select_account consent",
            clientId: env.GOOGLE_CLIENT_ID,
            clientSecret: env.GOOGLE_CLIENT_SECRET,
            getUserInfo: async token => {
              const response = await fetch("https://www.googleapis.com/oauth2/v2/userinfo", {
                headers: {
                  Authorization: `Bearer ${token.accessToken}`,
                },
              });
              if (!response.ok) {
                throw new Error(
                  `Google userinfo request failed: ${response.status} ${response.statusText}`
                );
              }
              const profile = await response.json();
              return {
                user: {
                  id: profile.id,
                  name: profile.name,
                  email: profile.email,
                  image: profile.picture,
                  emailVerified: profile.verified_email,
                },
                data: profile,
              };
            },
          },
        }
      : {},
  rateLimit: {
    window: 60,
    max: 20,
    storage: "memory",
  },

  plugins: [
    passkey({
      rpName: "TanStack Start Template",
      rpID: new URL(env.BETTER_AUTH_URL).hostname,
      origin: env.BETTER_AUTH_URL,
    }),
    emailOTP({
      async sendVerificationOTP({ email, otp, type }) {
        const subject = type === "email-verification" ? "Verify your email" : "Your sign-in code";
        logger.info("Sending OTP email", { email, type });
        await sendEmail(email, subject, createElement(OtpEmail, { otp, type }));
      },
      expiresIn: 600,
    }),
    tanstackStartCookies(),
  ],
});
