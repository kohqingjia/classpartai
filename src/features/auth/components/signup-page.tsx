import { Page } from "#/components/custom/page";
import { SignupForm } from "#/features/auth/components/signup-form";

export function SignupPage() {
  return (
    <Page width="sm" className="py-20 md:py-28">
      <SignupForm />
    </Page>
  );
}
