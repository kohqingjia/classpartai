import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { VerifyOtpForm } from "#/features/auth/components/verify-otp";

const mockNavigate = vi.fn<() => void>();

vi.mock("@tanstack/react-router", () => ({
  Link: ({ children, to }: { children: React.ReactNode; to: string }) => (
    <a href={to}>{children}</a>
  ),
  useNavigate: () => mockNavigate,
}));

vi.mock("#/lib/auth-client", () => ({
  authClient: {
    signIn: {
      emailOtp: vi
        .fn<() => Promise<{ data: null; error: null }>>()
        .mockResolvedValue({ data: null, error: null }),
    },
    passkey: {
      addPasskey: vi
        .fn<() => Promise<{ data: null; error: null }>>()
        .mockResolvedValue({ data: null, error: null }),
    },
  },
}));

function renderForm(flow: "sign-in" | "sign-up") {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <VerifyOtpForm email="user@example.com" flow={flow} />
    </QueryClientProvider>
  );
}

describe("VerifyOtpForm component", () => {
  it("renders verification code input and email target", () => {
    renderForm("sign-in");

    expect(screen.getByText("Check your email")).toBeTruthy();
    expect(screen.getByText("user@example.com")).toBeTruthy();
    expect(screen.getByLabelText(/verification code/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /verify code/i })).toBeTruthy();
  });

  it("shows validation error when entering an invalid length OTP", async () => {
    renderForm("sign-in");

    const otpInput = screen.getByLabelText(/verification code/i);
    fireEvent.change(otpInput, { target: { value: "123" } });

    fireEvent.click(screen.getByRole("button", { name: /verify code/i }));

    await waitFor(() => {
      expect(otpInput.getAttribute("aria-invalid")).toBe("true");
      expect(screen.getByRole("alert")).toBeTruthy();
    });
  });

  it("submits 6-digit OTP and navigates to home for sign-in flow", async () => {
    const { authClient } = await import("#/lib/auth-client");
    const user = userEvent.setup();
    renderForm("sign-in");

    const otpInput = screen.getByLabelText(/verification code/i);
    await user.type(otpInput, "123456");

    const submitButton = screen.getByRole("button", { name: /verify code/i });
    await user.click(submitButton);

    await waitFor(() => {
      expect(authClient.signIn.emailOtp).toHaveBeenCalledWith({
        email: "user@example.com",
        otp: "123456",
      });
      expect(mockNavigate).toHaveBeenCalledWith({ to: "/" });
    });
  });

  it("displays server error when OTP verification fails", async () => {
    const { authClient } = await import("#/lib/auth-client");
    vi.mocked(authClient.signIn.emailOtp).mockResolvedValueOnce({
      data: null,
      error: { message: "Invalid OTP code", status: 400, statusText: "Bad Request" } as never,
    });

    const user = userEvent.setup();
    renderForm("sign-in");

    const otpInput = screen.getByLabelText(/verification code/i);
    await user.type(otpInput, "000000");

    const submitButton = screen.getByRole("button", { name: /verify code/i });
    await user.click(submitButton);

    await waitFor(() => {
      expect(screen.getByText("Invalid OTP code")).toBeTruthy();
    });
  });

  it("shows PasskeyPrompt on sign-up flow after OTP verification and allows registering passkey", async () => {
    const { authClient } = await import("#/lib/auth-client");
    const user = userEvent.setup();
    renderForm("sign-up");

    const otpInput = screen.getByLabelText(/verification code/i);
    await user.type(otpInput, "654321");

    const submitButton = screen.getByRole("button", { name: /verify code/i });
    await user.click(submitButton);

    await waitFor(() => {
      expect(screen.getByText("Set up a passkey")).toBeTruthy();
    });

    const passkeyButton = screen.getByRole("button", { name: /set up passkey/i });
    await user.click(passkeyButton);

    await waitFor(() => {
      expect(authClient.passkey.addPasskey).toHaveBeenCalledWith({
        name: "user@example.com",
      });
      expect(mockNavigate).toHaveBeenCalledWith({ to: "/" });
    });
  });

  it("allows skipping passkey registration in PasskeyPrompt", async () => {
    const user = userEvent.setup();
    renderForm("sign-up");

    const otpInput = screen.getByLabelText(/verification code/i);
    await user.type(otpInput, "654321");

    const submitButton = screen.getByRole("button", { name: /verify code/i });
    await user.click(submitButton);

    await waitFor(() => {
      expect(screen.getByText("Set up a passkey")).toBeTruthy();
    });

    const skipButton = screen.getByRole("button", { name: /skip for now/i });
    await user.click(skipButton);

    expect(mockNavigate).toHaveBeenCalledWith({ to: "/" });
  });

  it("displays server error when passkey setup fails", async () => {
    const { authClient } = await import("#/lib/auth-client");
    vi.mocked(authClient.passkey.addPasskey).mockResolvedValueOnce({
      data: null,
      error: { message: "Passkey setup failed", status: 400, statusText: "Bad Request" } as never,
    });

    const user = userEvent.setup();
    renderForm("sign-up");

    await user.type(screen.getByLabelText(/verification code/i), "654321");
    await user.click(screen.getByRole("button", { name: /verify code/i }));

    await waitFor(() => {
      expect(screen.getByText("Set up a passkey")).toBeTruthy();
    });

    await user.click(screen.getByRole("button", { name: /set up passkey/i }));

    await waitFor(() => {
      expect(screen.getByText("Passkey setup failed")).toBeTruthy();
    });
    expect(mockNavigate).not.toHaveBeenCalled();
  });
});
