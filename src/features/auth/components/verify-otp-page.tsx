import { getRouteApi } from "@tanstack/react-router";
import { Page } from "#/components/custom/page";
import { VerifyOtpForm } from "#/features/auth/components/verify-otp";

const routeApi = getRouteApi("/verify-otp");

export function VerifyOtpPage() {
  const { email, flow } = routeApi.useSearch();

  return (
    <Page width="sm" className="py-20 md:py-28">
      <VerifyOtpForm email={email} flow={flow} />
    </Page>
  );
}
