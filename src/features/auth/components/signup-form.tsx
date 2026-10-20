import { cn } from "#/lib/utils";
import { Button } from "#/components/ui/button";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
  FieldSeparator,
} from "#/components/ui/field";
import { Input } from "#/components/ui/input";
import { Link, useNavigate, useRouter } from "@tanstack/react-router";
import { useForm } from "@tanstack/react-form-start";
import { z } from "zod";
import { authClient } from "#/lib/auth-client";
import { PasswordSchema } from "#/features/auth/schema/password";
import { FormError } from "#/components/custom/form-error";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

const schema = z.object({
  email: z.email("Enter a valid email address"),
  password: PasswordSchema,
});

export function SignupForm({ className, ...props }: React.ComponentProps<"div">) {
  const navigate = useNavigate();
  const router = useRouter();
  const [verifyEmail, setVerifyEmail] = useState<string | null>(null);

  const form = useForm({
    defaultValues: { email: "", password: "" },
    validators: { onSubmit: schema },
    onSubmit: async ({ value, formApi }) => {
      // ponytail: name is "" to match what the email-OTP flow stores; add a field if profiles need one.
      const { error } = await authClient.signUp.email({
        name: "",
        email: value.email,
        password: value.password,
      });
      if (error) {
        formApi.setErrorMap({
          onSubmit: {
            form: error.message ?? "Could not create your account. Try again.",
            fields: {},
          },
        });
        return;
      }
      // Re-runs the root's beforeLoad so the header picks up the session the sign-up created.
      await router.invalidate();
      setVerifyEmail(value.email);
    },
  });

  const sendSignupCode = useMutation({
    mutationFn: async (email: string) => {
      if (!z.email().safeParse(email).success) {
        throw new Error("Enter a valid email address to receive a code.");
      }
      const { error } = await authClient.emailOtp.sendVerificationOtp({ email, type: "sign-in" });
      if (error) throw new Error(error.message ?? "Failed to send code. Try again.");
    },
    onSuccess: (_data, email) =>
      navigate({ to: "/verify-otp", search: { email, flow: "sign-up" } }),
    onError: error => form.setErrorMap({ onSubmit: { form: error.message, fields: {} } }),
  });

  const handleOtpSignUp = () => sendSignupCode.mutate(form.getFieldValue("email"));

  if (verifyEmail) {
    return (
      <div className={cn("flex flex-col gap-5", className)} {...props}>
        <FieldGroup>
          <div className="flex flex-col items-center gap-1.5 text-center">
            <h1 className="font-heading text-2xl font-semibold tracking-tight">Check your email</h1>
            <FieldDescription>
              We sent a verification link to <strong>{verifyEmail}</strong>. Verify your address to
              keep the password you just set — signing in with an email code before you verify
              clears it.
            </FieldDescription>
          </div>
          <Field>
            <Button type="button" onClick={() => void navigate({ to: "/" })}>
              Continue
            </Button>
          </Field>
        </FieldGroup>
      </div>
    );
  }

  return (
    <div className={cn("flex flex-col gap-5", className)} {...props}>
      <form
        onSubmit={e => {
          e.preventDefault();
          void form.handleSubmit();
        }}
      >
        <FieldGroup>
          <div className="flex flex-col items-center gap-1.5 text-center">
            <h1 className="font-heading text-2xl font-semibold tracking-tight">
              Create an account
            </h1>
            <FieldDescription>
              Already have an account? <Link to="/login">Sign in</Link>
            </FieldDescription>
          </div>

          <form.Field name="email">
            {field => (
              <Field>
                <FieldLabel htmlFor="email">Email</FieldLabel>
                <Input
                  id="email"
                  type="email"
                  autoComplete="username webauthn"
                  placeholder="you@example.com"
                  value={field.state.value}
                  onChange={e => field.handleChange(e.target.value)}
                  onBlur={field.handleBlur}
                  aria-invalid={field.state.meta.errors.length > 0}
                />
                <FieldError errors={field.state.meta.errors} />
              </Field>
            )}
          </form.Field>

          <form.Field name="password">
            {field => (
              <Field>
                <FieldLabel htmlFor="password">Password</FieldLabel>
                <Input
                  id="password"
                  type="password"
                  autoComplete="new-password"
                  value={field.state.value}
                  onChange={e => field.handleChange(e.target.value)}
                  onBlur={field.handleBlur}
                  aria-invalid={field.state.meta.errors.length > 0}
                />
                <FieldError errors={field.state.meta.errors} />
                <FieldDescription>
                  At least 8 characters, including a number and a symbol.
                </FieldDescription>
              </Field>
            )}
          </form.Field>

          <form.Subscribe selector={s => s.errorMap.onSubmit}>
            {formError => <FormError error={formError} />}
          </form.Subscribe>

          <form.Subscribe selector={s => s.isSubmitting}>
            {isSubmitting => (
              <Field>
                <Button type="submit" disabled={isSubmitting}>
                  {isSubmitting ? "Creating account..." : "Create account"}
                </Button>
              </Field>
            )}
          </form.Subscribe>

          <FieldSeparator>Or</FieldSeparator>

          <div className="grid gap-3">
            <Button
              variant="outline"
              type="button"
              disabled={sendSignupCode.isPending}
              onClick={handleOtpSignUp}
            >
              {sendSignupCode.isPending ? "Sending code..." : "Sign up with an email code"}
            </Button>
            <Button
              variant="outline"
              type="button"
              onClick={() =>
                void authClient.signIn.social({ provider: "google", callbackURL: "/" })
              }
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" className="size-4">
                <path
                  d="M12.48 10.92v3.28h7.84c-.24 1.84-.853 3.187-1.787 4.133-1.147 1.147-2.933 2.4-6.053 2.4-4.827 0-8.6-3.893-8.6-8.72s3.773-8.72 8.6-8.72c2.6 0 4.507 1.027 5.907 2.347l2.307-2.307C18.747 1.44 16.133 0 12.48 0 5.867 0 .307 5.387.307 12s5.56 12 12.173 12c3.573 0 6.267-1.173 8.373-3.36 2.16-2.16 2.84-5.213 2.84-7.667 0-.76-.053-1.467-.173-2.053H12.48z"
                  fill="currentColor"
                />
              </svg>
              Continue with Google
            </Button>
          </div>
        </FieldGroup>
      </form>
    </div>
  );
}
