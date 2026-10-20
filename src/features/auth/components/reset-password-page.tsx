import { getRouteApi } from "@tanstack/react-router";
import { Page } from "#/components/custom/page";
import { ResetPasswordForm } from "#/features/auth/components/reset-password-form";

const routeApi = getRouteApi("/reset-password");

export function ResetPasswordPage() {
  const { token, error } = routeApi.useSearch();

  return (
    <Page width="sm" className="py-20 md:py-28">
      <ResetPasswordForm token={token} error={error} />
    </Page>
  );
}
