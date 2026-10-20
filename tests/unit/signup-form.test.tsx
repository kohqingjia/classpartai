import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SignupForm } from "#/features/auth/components/signup-form";

const mockNavigate = vi.fn<() => void>();
const mockInvalidate = vi.fn<() => Promise<void>>().mockResolvedValue(undefined);

vi.mock("@tanstack/react-router", () => ({
  Link: ({ children, to }: { children: React.ReactNode; to: string }) => (
    <a href={to}>{children}</a>
  ),
  useNavigate: () => mockNavigate,
  useRouter: () => ({ invalidate: mockInvalidate }),
}));

vi.mock("#/lib/auth-client", () => ({
  authClient: {
    signIn: {
      social: vi
        .fn<() => Promise<{ data: null; error: null }>>()
        .mockResolvedValue({ data: null, error: null }),
    },
    signUp: {
      email: vi
        .fn<() => Promise<{ data: null; error: null }>>()
        .mockResolvedValue({ data: null, error: null }),
    },
    emailOtp: {
      sendVerificationOtp: vi
        .fn<() => Promise<{ data: null; error: null }>>()
        .mockResolvedValue({ data: null, error: null }),
    },
  },
}));

function renderForm() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <SignupForm />
    </QueryClientProvider>
  );
}

describe("SignupForm component", () => {
  it("renders email and password inputs, create account button, and Google OAuth button", () => {
    renderForm();

    expect(screen.getByText("Create an account")).toBeTruthy();
    expect(screen.getByLabelText(/email/i)).toBeTruthy();
    expect(screen.getByLabelText(/password/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /create account/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /sign up with an email code/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /continue with google/i })).toBeTruthy();
  });

  it("shows validation error when submitting an invalid email", async () => {
    renderForm();

    const emailInput = screen.getByLabelText(/email/i);
    // `a@b` passes the browser's own `type="email"` constraint (which blocks submission in a
    // browser), and fails the app's Zod schema — the error the form is expected to surface.
    fireEvent.change(emailInput, { target: { value: "a@b" } });

    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => {
      expect(emailInput.getAttribute("aria-invalid")).toBe("true");
      expect(screen.getByText("Enter a valid email address")).toBeTruthy();
    });
  });

  it("rejects a password shorter than 8 characters", async () => {
    const { authClient } = await import("#/lib/auth-client");
    vi.mocked(authClient.signUp.email).mockClear();
    const user = userEvent.setup();
    renderForm();

    await user.type(screen.getByLabelText(/email/i), "newuser@example.com");
    await user.type(screen.getByLabelText(/password/i), "short");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => {
      expect(screen.getByText("Password must be at least 8 characters")).toBeTruthy();
    });
    expect(authClient.signUp.email).not.toHaveBeenCalled();
  });

  it("rejects a long password with no number or symbol", async () => {
    const { authClient } = await import("#/lib/auth-client");
    vi.mocked(authClient.signUp.email).mockClear();
    const user = userEvent.setup();
    renderForm();

    await user.type(screen.getByLabelText(/email/i), "newuser@example.com");
    await user.type(screen.getByLabelText(/password/i), "alllowercaseletters");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => {
      expect(screen.getByText("Password must contain at least one number")).toBeTruthy();
      expect(screen.getByText("Password must contain at least one symbol")).toBeTruthy();
    });
    expect(authClient.signUp.email).not.toHaveBeenCalled();
  });

  it("creates an account with email and password", async () => {
    const { authClient } = await import("#/lib/auth-client");
    const user = userEvent.setup();
    renderForm();

    await user.type(screen.getByLabelText(/email/i), "newuser@example.com");
    await user.type(screen.getByLabelText(/password/i), "long-enough-pass1!");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => {
      expect(authClient.signUp.email).toHaveBeenCalledWith({
        name: "",
        email: "newuser@example.com",
        password: "long-enough-pass1!",
      });
    });
  });

  it("tells the new user to verify their email instead of navigating away", async () => {
    const user = userEvent.setup();
    renderForm();

    await user.type(screen.getByLabelText(/email/i), "newuser@example.com");
    await user.type(screen.getByLabelText(/password/i), "long-enough-pass1!");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => {
      expect(screen.getByText("Check your email")).toBeTruthy();
      expect(
        screen.getByText(/signing in with an email code before you verify clears it/i)
      ).toBeTruthy();
    });
    expect(mockNavigate).not.toHaveBeenCalled();
    // The header reads the session from route context, so the in-place sign-up must re-resolve it.
    expect(mockInvalidate).toHaveBeenCalled();
  });

  it("displays server error message when sign-up fails", async () => {
    const { authClient } = await import("#/lib/auth-client");
    vi.mocked(authClient.signUp.email).mockResolvedValueOnce({
      data: null,
      error: { message: "Account already exists", status: 400, statusText: "Bad Request" } as never,
    });

    const user = userEvent.setup();
    renderForm();

    await user.type(screen.getByLabelText(/email/i), "existing@example.com");
    await user.type(screen.getByLabelText(/password/i), "long-enough-pass1!");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => {
      expect(screen.getByText("Account already exists")).toBeTruthy();
    });
  });

  it("sends an OTP and navigates to verify-otp when signing up with a code", async () => {
    const { authClient } = await import("#/lib/auth-client");
    const user = userEvent.setup();
    renderForm();

    await user.type(screen.getByLabelText(/email/i), "newuser@example.com");
    await user.click(screen.getByRole("button", { name: /sign up with an email code/i }));

    await waitFor(() => {
      expect(authClient.emailOtp.sendVerificationOtp).toHaveBeenCalledWith({
        email: "newuser@example.com",
        type: "sign-in",
      });
      expect(mockNavigate).toHaveBeenCalledWith({
        to: "/verify-otp",
        search: { email: "newuser@example.com", flow: "sign-up" },
      });
    });
  });

  it("triggers Google social sign-in when clicking Continue with Google", async () => {
    const { authClient } = await import("#/lib/auth-client");
    const user = userEvent.setup();
    renderForm();

    const googleButton = screen.getByRole("button", { name: /continue with google/i });
    await user.click(googleButton);

    await waitFor(() => {
      expect(authClient.signIn.social).toHaveBeenCalledWith({
        provider: "google",
        callbackURL: "/",
      });
    });
  });

  it("displays server error when sending a sign-up code fails", async () => {
    const { authClient } = await import("#/lib/auth-client");
    vi.mocked(authClient.emailOtp.sendVerificationOtp).mockResolvedValueOnce({
      data: null,
      error: {
        message: "Email service unavailable",
        status: 503,
        statusText: "Unavailable",
      } as never,
    });

    const user = userEvent.setup();
    renderForm();

    await user.type(screen.getByLabelText(/email/i), "newuser@example.com");
    await user.click(screen.getByRole("button", { name: /sign up with an email code/i }));

    await waitFor(() => {
      expect(screen.getByText("Email service unavailable")).toBeTruthy();
    });
    expect(mockNavigate).not.toHaveBeenCalled();
  });
});
