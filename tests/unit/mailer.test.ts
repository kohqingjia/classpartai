import { createMailer, sendEmail } from "#/lib/mailer.server";
import * as React from "react";
import { beforeEach, describe, expect, test, vi } from "vitest";

const { mockEmailsSend, mockEnv, mockSendMail, mockTransportClose } = vi.hoisted(() => {
  const env: { RESEND_API_KEY?: string; EMAIL_FROM?: string; SMTP_URL?: string } = {
    RESEND_API_KEY: "re_test_key",
    EMAIL_FROM: "Sender <from@example.com>",
  };
  return {
    mockEmailsSend: vi.fn<(...args: unknown[]) => unknown>(),
    mockEnv: env,
    mockSendMail: vi.fn<(...args: unknown[]) => unknown>(),
    mockTransportClose: vi.fn<() => void>(),
  };
});

vi.mock("resend", () => ({
  Resend: vi.fn<(...args: unknown[]) => unknown>(function () {
    return { emails: { send: mockEmailsSend } };
  }),
}));

vi.mock("nodemailer", () => ({
  createTransport: vi.fn<(...args: unknown[]) => unknown>(function () {
    return { sendMail: mockSendMail, close: mockTransportClose };
  }),
}));

vi.mock("#/env", () => ({ env: mockEnv }));

vi.mock("#/lib/logger", () => ({
  logger: {
    info: vi.fn<() => void>(),
    error: vi.fn<() => void>(),
  },
}));

describe("createMailer", () => {
  test("returns null when apiKey is undefined", () => {
    expect(createMailer(undefined)).toBeNull();
  });

  test("returns null when apiKey is empty string", () => {
    expect(createMailer("")).toBeNull();
  });

  test("returns Resend instance when apiKey is provided", () => {
    expect(createMailer("re_abc123")).not.toBeNull();
  });
});

describe("sendEmail", () => {
  const element = React.createElement("div");

  beforeEach(() => {
    vi.clearAllMocks();
    mockEnv.RESEND_API_KEY = "re_test_key";
    mockEnv.EMAIL_FROM = "Sender <from@example.com>";
    mockEnv.SMTP_URL = undefined;
  });

  test("throws when RESEND_API_KEY is not set", async () => {
    mockEnv.RESEND_API_KEY = undefined;
    await expect(sendEmail("to@example.com", "Subject", element)).rejects.toThrow(
      "RESEND_API_KEY is not configured"
    );
  });

  test("sends email with correct params and returns data", async () => {
    const data = { id: "email_123" };
    mockEmailsSend.mockResolvedValue({ data, error: null });

    const result = await sendEmail("to@example.com", "Hello", element);

    expect(mockEmailsSend).toHaveBeenCalledWith({
      from: "Sender <from@example.com>",
      to: "to@example.com",
      subject: "Hello",
      react: element,
    });
    expect(result).toEqual(data);
  });

  test("uses default from address when EMAIL_FROM is not set", async () => {
    mockEnv.EMAIL_FROM = undefined;
    mockEmailsSend.mockResolvedValue({ data: { id: "x" }, error: null });

    await sendEmail("to@example.com", "Hello", element);

    expect(mockEmailsSend).toHaveBeenCalledWith(
      expect.objectContaining({ from: "TanStack Start <onboarding@resend.dev>" })
    );
  });

  test("throws when Resend returns an error", async () => {
    mockEmailsSend.mockResolvedValue({ data: null, error: { message: "Invalid API key" } });

    await expect(sendEmail("to@example.com", "Subject", element)).rejects.toThrow(
      "Failed to send email"
    );
  });

  test("relays over SMTP and bypasses Resend when SMTP_URL is set", async () => {
    mockEnv.SMTP_URL = "smtp://localhost:1025";
    mockSendMail.mockResolvedValue({ messageId: "smtp_123" });

    const result = await sendEmail("to@example.com", "Hello", element);

    expect(mockSendMail).toHaveBeenCalledWith(
      expect.objectContaining({ to: "to@example.com", subject: "Hello" })
    );
    expect(mockTransportClose).toHaveBeenCalled();
    expect(result).toEqual({ id: "smtp_123" });
    expect(mockEmailsSend).not.toHaveBeenCalled();
  });
});
