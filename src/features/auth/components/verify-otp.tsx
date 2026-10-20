import { cn } from "#/lib/utils";
import { Button } from "#/components/ui/button";
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "#/components/ui/field";
import { Input } from "#/components/ui/input";
import { Link, useNavigate } from "@tanstack/react-router";
import { useForm } from "@tanstack/react-form-start";
import { z } from "zod";
import { authClient } from "#/lib/auth-client";
import { FormError } from "#/components/custom/form-error";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

const schema = z.object({
  otp: z.string().length(6, "Enter the 6-digit code").regex(/^\d+$/, "Code must be digits only"),
});

interface VerifyOtpFormProps extends Omit<React.ComponentProps<"div">, "children"> {
  email: string;
  flow: "sign-in" | "sign-up";
}

export function VerifyOtpForm({ email, flow, className, ...props }: VerifyOtpFormProps) {
  const navigate = useNavigate();
  const [showPasskeyPrompt, setShowPasskeyPrompt] = useState(false);

  const form = useForm({
    defaultValues: { otp: "" },
    validators: { onSubmit: schema },
    onSubmit: async ({ value, formApi }) => {
      const { error } = await authClient.signIn.emailOtp({
        email,
        otp: value.otp,
      });
      if (error) {
        formApi.setErrorMap({
          onSubmit: { form: error.message ?? "Invalid or expired code. Try again.", fields: {} },
        });
        return;
      }
      if (flow === "sign-up") {
        setShowPasskeyPrompt(true);
      } else {
        await navigate({ to: "/" });
      }
    },
  });

  const registerPasskey = useMutation({
    mutationFn: async () => {
      const result = await authClient.passkey.addPasskey({ name: email });
      if (result.error) throw new Error(result.error.message ?? "Failed to set up passkey.");
    },
    onSuccess: () => navigate({ to: "/" }),
    onError: error => form.setErrorMap({ onSubmit: { form: error.message, fields: {} } }),
  });

  if (showPasskeyPrompt) {
    return (
      <form.Subscribe selector={s => s.errorMap.onSubmit}>
        {formError => (
          <PasskeyPrompt
            email={email}
            error={formError}
            loading={registerPasskey.isPending}
            onRegister={() => registerPasskey.mutate()}
            onSkip={() => void navigate({ to: "/" })}
          />
        )}
      </form.Subscribe>
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
            <h1 className="font-heading text-2xl font-semibold tracking-tight">Check your email</h1>
            <FieldDescription>
              We sent a 6-digit code to <strong>{email}</strong>
            </FieldDescription>
          </div>

          <form.Field name="otp">
            {field => (
              <Field>
                <FieldLabel htmlFor="otp">Verification code</FieldLabel>
                <Input
                  id="otp"
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  placeholder="000000"
                  maxLength={6}
                  value={field.state.value}
                  onChange={e => {
                    const digits = e.target.value.replace(/\D/g, "").slice(0, 6);
                    field.handleChange(digits);
                  }}
                  onBlur={field.handleBlur}
                  aria-invalid={field.state.meta.errors.length > 0}
                  variant="otp"
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
                  {isSubmitting ? "Verifying..." : "Verify code"}
                </Button>
              </Field>
            )}
          </form.Subscribe>

          <FieldDescription className="text-center">
            Wrong email? <Link to={flow === "sign-up" ? "/signup" : "/login"}>Go back</Link>
          </FieldDescription>
        </FieldGroup>
      </form>
    </div>
  );
}

function PasskeyPrompt({
  email,
  error,
  loading,
  onRegister,
  onSkip,
}: {
  email: string;
  error: unknown;
  loading: boolean;
  onRegister: () => void;
  onSkip: () => void;
}) {
  return (
    <div className="flex flex-col gap-5">
      <FieldGroup>
        <div className="flex flex-col items-center gap-1.5 text-center">
          <h1 className="font-heading text-2xl font-semibold tracking-tight">Set up a passkey</h1>
          <FieldDescription>
            Use your device biometrics or PIN to sign in faster next time. No password needed.
          </FieldDescription>
        </div>

        <FormError error={error} />

        <Field>
          <Button type="button" disabled={loading} onClick={onRegister}>
            {loading ? "Setting up..." : "Set up passkey"}
          </Button>
        </Field>

        <Field>
          <Button variant="ghost" type="button" onClick={onSkip}>
            Skip for now
          </Button>
        </Field>

        <FieldDescription className="text-center">
          Signed in as <strong>{email}</strong>
        </FieldDescription>
      </FieldGroup>
    </div>
  );
}
