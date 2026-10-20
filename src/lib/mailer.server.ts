import { Resend } from "resend";
import * as React from "react";
import { logger } from "#/lib/logger";
import { maskEmail } from "#/lib/utils";
import { env } from "#/env";

export function createMailer(apiKey: string | undefined): Resend | null {
  if (!apiKey) return null;
  return new Resend(apiKey);
}

let cachedApiKey: string | undefined;
let cachedMailer: Resend | null = null;

export function getMailer(): Resend | null {
  if (cachedMailer && cachedApiKey === env.RESEND_API_KEY) {
    return cachedMailer;
  }
  cachedApiKey = env.RESEND_API_KEY;
  cachedMailer = createMailer(env.RESEND_API_KEY);
  return cachedMailer;
}

export async function sendEmail(to: string, subject: string, react: React.ReactElement) {
  const maskedTo = maskEmail(to);

  logger.info("Sending email", { to: maskedTo, subject });

  const from = env.EMAIL_FROM ?? "TanStack Start <onboarding@resend.dev>";

  // SMTP_URL is set only for local/E2E runs, where a capture server (Mailpit) stands in for
  // Resend's HTTP API. Production leaves it unset and takes the Resend branch below.
  if (env.SMTP_URL) {
    const [{ createTransport }, { render }] = await Promise.all([
      import("nodemailer"),
      import("@react-email/render"),
    ]);
    const transport = createTransport(env.SMTP_URL);
    try {
      const info = await transport.sendMail({ from, to, subject, html: await render(react) });
      logger.info("Successfully sent email via SMTP", { to: maskedTo, id: info.messageId });
      return { id: info.messageId };
    } finally {
      transport.close();
    }
  }

  const client = getMailer();

  if (!client) {
    throw new Error(
      "RESEND_API_KEY is not configured. Set it in your environment to enable email sending."
    );
  }

  const { data, error } = await client.emails.send({
    from,
    to,
    subject,
    react,
  });

  if (error) {
    // Resend's message can echo the recipient address, so only the error's
    // stable identifiers are logged; the thrown error keeps the full payload
    // for Sentry.
    logger.error("Failed to send email", { to: maskedTo, name: error.name });
    throw new Error(`Failed to send email: ${JSON.stringify(error)}`);
  }

  logger.info("Successfully sent email", { to: maskedTo, id: data.id });
  return data;
}
