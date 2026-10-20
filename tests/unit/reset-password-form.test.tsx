import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ResetPasswordForm } from "#/features/auth/components/reset-password-form";

const mockNavigate = vi.fn<() => void>();

vi.mock("@tanstack/react-router", () => ({
  Link: ({ children, to }: { children: React.ReactNode; to: string }) => (
    <a href={to}>{children}</a>
  ),
  useNavigate: () => mockNavigate,
}));

vi.mock("#/lib/auth-client", () => ({
  authClient: {
    requestPasswordReset: vi
      .fn<() => Promise<{ data: null; error: null }>>()
      .mockResolvedValue({ data: null, error: null }),
    resetPassword: vi
      .fn<() => Promise<{ data: null; error: null }>>()
      .mockResolvedValue({ data: null, error: null }),
  },
}));

describe("ResetPasswordForm component", () => {
  it("requests a reset link and confirms it was sent", async () => {
    const { authClient } = await import("#/lib/auth-client");
    const user = userEvent.setup();
    render(<ResetPasswordForm />);

    await user.type(screen.getByLabelText(/email/i), "test@example.com");
    await user.click(screen.getByRole("button", { name: /send reset link/i }));

    await waitFor(() => {
      expect(authClient.requestPasswordReset).toHaveBeenCalledWith({
        email: "test@example.com",
        redirectTo: "/reset-password",
      });
      expect(screen.getByText("Check your email")).toBeTruthy();
    });
  });

  it("explains an expired link and still offers a new one", () => {
    render(<ResetPasswordForm error="INVALID_TOKEN" />);

    expect(screen.getByText(/invalid or has expired/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /send reset link/i })).toBeTruthy();
  });

  it("submits the new password with the token and returns to sign-in", async () => {
    const { authClient } = await import("#/lib/auth-client");
    const user = userEvent.setup();
    render(<ResetPasswordForm token="tok-123" />);

    await user.type(screen.getByLabelText(/new password/i), "long-enough-pass1!");
    await user.click(screen.getByRole("button", { name: /save password/i }));

    await waitFor(() => {
      expect(authClient.resetPassword).toHaveBeenCalledWith({
        newPassword: "long-enough-pass1!",
        token: "tok-123",
      });
      expect(mockNavigate).toHaveBeenCalledWith({ to: "/login" });
    });
  });

  it("rejects a new password shorter than 8 characters", async () => {
    const { authClient } = await import("#/lib/auth-client");
    vi.mocked(authClient.resetPassword).mockClear();
    const user = userEvent.setup();
    render(<ResetPasswordForm token="tok-123" />);

    await user.type(screen.getByLabelText(/new password/i), "short");
    await user.click(screen.getByRole("button", { name: /save password/i }));

    await waitFor(() => {
      expect(screen.getByText("Password must be at least 8 characters")).toBeTruthy();
    });
    expect(authClient.resetPassword).not.toHaveBeenCalled();
  });
});
