import { Button } from "#/components/ui/button";
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "#/components/ui/field";
import { Input } from "#/components/ui/input";
import { Link, useNavigate } from "@tanstack/react-router";
import { useForm } from "@tanstack/react-form-start";
import { z } from "zod";
import { authClient } from "#/lib/auth-client";
import { PasswordSchema } from "#/features/auth/schema/password";
import { FormError } from "#/components/custom/form-error";
import { useState } from "react";

/**
 * `token` is present when the user arrived from the emailed link; Better Auth sends `error`
 * (`INVALID_TOKEN`) instead when that link expired or was already used.
 */
export function ResetPasswordForm({ token, error }: { token?: string; error?: string }) {
  return token ? <SetNewPassword token={token} /> : <RequestReset expired={Boolean(error)} />;
}

function RequestReset({ expired }: { expired: boolean }) {
  const [sent, setSent] = useState(false);

  const form = useForm({
    defaultValues: { email: "" },
    validators: { onSubmit: z.object({ email: z.email("Enter a valid email address") }) },
    onSubmit: async ({ value, formApi }) => {
      const { error } = await authClient.requestPasswordReset({
        email: value.email,
        redirectTo: "/reset-password",
      });
      if (error) {
        formApi.setErrorMap({
          onSubmit: { form: error.message ?? "Failed to send reset link. Try again.", fields: {} },
        });
        return;
      }
      setSent(true);
    },
  });

  if (sent) {
    return (
      <FieldGroup>
        <div className="flex flex-col items-center gap-1.5 text-center">
          <h1 className="font-heading text-2xl font-semibold tracking-tight">Check your email</h1>
          <FieldDescription>
            If an account exists for that address, we sent a link to set a new password. It expires
            in 1 hour.
          </FieldDescription>
        </div>
        <FieldDescription className="text-center">
          <Link to="/login">Back to sign in</Link>
        </FieldDescription>
      </FieldGroup>
    );
  }

  return (
    <form
      onSubmit={e => {
        e.preventDefault();
        void form.handleSubmit();
      }}
    >
      <FieldGroup>
        <div className="flex flex-col items-center gap-1.5 text-center">
          <h1 className="font-heading text-2xl font-semibold tracking-tight">
            Reset your password
          </h1>
          <FieldDescription>
            {expired
              ? "That reset link is invalid or has expired. Request a new one."
              : "Enter your email and we will send you a link to set a new password."}
          </FieldDescription>
        </div>

        <form.Field name="email">
          {field => (
            <Field>
              <FieldLabel htmlFor="email">Email</FieldLabel>
              <Input
                id="email"
                type="email"
                autoComplete="username"
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

        <form.Subscribe selector={s => s.errorMap.onSubmit}>
          {formError => <FormError error={formError} />}
        </form.Subscribe>

        <form.Subscribe selector={s => s.isSubmitting}>
          {isSubmitting => (
            <Field>
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting ? "Sending link..." : "Send reset link"}
              </Button>
            </Field>
          )}
        </form.Subscribe>

        <FieldDescription className="text-center">
          Remembered it? <Link to="/login">Sign in</Link>
        </FieldDescription>
      </FieldGroup>
    </form>
  );
}

function SetNewPassword({ token }: { token: string }) {
  const navigate = useNavigate();

  const form = useForm({
    defaultValues: { password: "" },
    validators: { onSubmit: z.object({ password: PasswordSchema }) },
    onSubmit: async ({ value, formApi }) => {
      const { error } = await authClient.resetPassword({ newPassword: value.password, token });
      if (error) {
        formApi.setErrorMap({
          onSubmit: {
            form: error.message ?? "Could not reset your password. Request a new link.",
            fields: {},
          },
        });
        return;
      }
      // resetPassword does not create a session, so send them through sign-in.
      await navigate({ to: "/login" });
    },
  });

  return (
    <form
      onSubmit={e => {
        e.preventDefault();
        void form.handleSubmit();
      }}
    >
      <FieldGroup>
        <div className="flex flex-col items-center gap-1.5 text-center">
          <h1 className="font-heading text-2xl font-semibold tracking-tight">Set a new password</h1>
          <FieldDescription>Choose a password you do not use anywhere else.</FieldDescription>
        </div>

        <form.Field name="password">
          {field => (
            <Field>
              <FieldLabel htmlFor="password">New password</FieldLabel>
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
                {isSubmitting ? "Saving..." : "Save password"}
              </Button>
            </Field>
          )}
        </form.Subscribe>
      </FieldGroup>
    </form>
  );
}
