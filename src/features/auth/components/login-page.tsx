import { Page } from "#/components/custom/page";
import { LoginForm } from "#/features/auth/components/login-form";

export function LoginPage() {
  return (
    <Page width="sm" className="py-20 md:py-28">
      <LoginForm />
    </Page>
  );
}
