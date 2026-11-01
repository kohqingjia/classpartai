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

  throw new Error("Paid email providers are disabled; configure local SMTP capture");
}

// Feedback transport is deliberately separate from drafting and never falls back to Resend.
export async function sendFeedbackToCapture(
  to: string,
  subject: string,
  text: string,
  messageId: string
) {
  if (env.FEEDBACK_DELIVERY !== "mailpit" || !env.SMTP_URL)
    throw new Error("Local capture delivery is disabled");
  const endpoint = new URL(env.SMTP_URL);
  if (
    endpoint.protocol !== "smtp:" ||
    !["127.0.0.1", "localhost", "[::1]"].includes(endpoint.hostname) ||
    endpoint.port !== "1025" ||
    endpoint.username ||
    endpoint.password
  )
    throw new Error("Feedback requires loopback Mailpit SMTP on port 1025");
  if (!/^[a-z0-9][a-z0-9._+-]{0,100}@example\.invalid$/i.test(to))
    throw new Error("Only example.invalid development recipients are permitted");
  const { createTransport } = await import("nodemailer");
  const transport = createTransport({
    host: endpoint.hostname,
    port: 1025,
    secure: false,
    connectionTimeout: 3000,
    greetingTimeout: 3000,
    socketTimeout: 7000,
  });
  try {
    const result = await transport.sendMail({
      from: "ClassPart AI <professor@example.invalid>",
      to,
      subject,
      text,
      messageId,
    });
    if (!result.accepted.some(address => address.toLowerCase() === to.toLowerCase()))
      throw Object.assign(new Error("SMTP recipient rejected"), { responseCode: 550 });
    return { messageId: result.messageId };
  } finally {
    transport.close();
  }
}
