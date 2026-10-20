import { getRouteApi, useNavigate } from "@tanstack/react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Trash2, KeyRound, Link } from "lucide-react";
import type { Passkey } from "@better-auth/passkey";
import { toast } from "sonner";

import { authClient } from "#/lib/auth-client";
import { accountOptions } from "#/features/auth/accounts";
import { Button } from "#/components/ui/button";
import { Skeleton } from "#/components/ui/skeleton";
import { Page } from "#/components/custom/page";

const routeApi = getRouteApi("/_authenticated/settings");

const PROVIDER_LABELS: Record<string, string> = {
  google: "Google",
  "email-otp": "Email OTP",
  credential: "Password",
};

function getProviderLabel(providerId: string) {
  return PROVIDER_LABELS[providerId] ?? providerId.charAt(0).toUpperCase() + providerId.slice(1);
}

export function SettingsPage() {
  const { user } = routeApi.useRouteContext();
  const navigate = useNavigate();

  async function handleDeleteAccount() {
    const { error } = await authClient.deleteUser({});
    if (error) {
      toast.error(error.message ?? "Failed to delete account");
      return;
    }
    await navigate({ to: "/" });
  }

  const { data: passkeys, isPending: passkeysPending } = authClient.useListPasskeys();
  const { data: accounts, status } = useQuery(accountOptions(user.id));
  const [confirmDelete, setConfirmDelete] = useState(false);
  const deletePasskey = useMutation({
    mutationFn: async (passkeyId: string) => {
      const { error } = await authClient.passkey.deletePasskey({ id: passkeyId });
      if (error) throw new Error(error.message ?? "Failed to delete passkey");
    },
    onError: error => toast.error(error.message),
  });

  return (
    <Page width="md" eyebrow="Settings" title="Account">
      <div className="mt-12 space-y-10">
        {/* Identity */}
        <SettingsSection title="Profile">
          <Row label="Email" value={user.email} />
          {user.name && <Row label="Name" value={user.name} />}
        </SettingsSection>

        {/* Linked providers */}
        <SettingsSection title="Linked providers">
          {status === "pending" ? (
            <div className="space-y-2" aria-busy="true">
              <IconRowSkeleton />
              <IconRowSkeleton />
            </div>
          ) : status === "error" ? (
            <p className="text-sm text-destructive" role="alert">
              Could not load linked providers.
            </p>
          ) : accounts.length === 0 ? (
            <p className="text-sm text-muted-foreground">No linked providers.</p>
          ) : (
            <ul className="space-y-2">
              {accounts.map(acct => (
                <li key={acct.id} className="flex items-center gap-2">
                  <Link className="size-4 text-muted-foreground" />
                  <span className="text-sm">{getProviderLabel(acct.providerId)}</span>
                </li>
              ))}
            </ul>
          )}
        </SettingsSection>

        {/* Passkeys */}
        <SettingsSection title="Passkeys">
          {passkeysPending ? (
            <div className="space-y-2" aria-busy="true">
              <IconRowSkeleton />
            </div>
          ) : !passkeys || passkeys.length === 0 ? (
            <p className="text-sm text-muted-foreground">No passkeys registered.</p>
          ) : (
            <ul className="space-y-2">
              {passkeys.map((pk: Passkey) => (
                <li key={pk.id} className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <KeyRound className="size-4 text-muted-foreground" />
                    <span className="text-sm">{pk.name ?? "Passkey"}</span>
                  </div>
                  <Button
                    type="button"
                    variant="destructive"
                    size="icon-sm"
                    disabled={deletePasskey.isPending && deletePasskey.variables === pk.id}
                    aria-label={`Delete passkey: ${pk.name ?? "Passkey"}`}
                    onClick={() => deletePasskey.mutate(pk.id)}
                  >
                    <Trash2 className="size-4" />
                  </Button>
                </li>
              ))}
            </ul>
          )}
          <div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="mt-3"
              onClick={() =>
                void (async () => {
                  const { error } = await authClient.passkey.addPasskey();
                  if (error) toast.error(error.message ?? "Failed to add passkey");
                })()
              }
            >
              <KeyRound className="size-4" />
              Add passkey
            </Button>
          </div>
        </SettingsSection>

        {/* Danger zone */}
        <SettingsSection title="Danger zone">
          {confirmDelete ? (
            <div className="space-y-3">
              <p className="text-sm text-destructive">
                This permanently deletes your account and all data. This cannot be undone.
              </p>
              <div className="flex gap-2">
                <Button variant="destructive" size="sm" onClick={() => void handleDeleteAccount()}>
                  Yes, delete my account
                </Button>
                <Button variant="outline" size="sm" onClick={() => setConfirmDelete(false)}>
                  Cancel
                </Button>
              </div>
            </div>
          ) : (
            <Button
              type="button"
              variant="destructive"
              size="sm"
              onClick={() => setConfirmDelete(true)}
            >
              <Trash2 className="size-4" />
              Delete account
            </Button>
          )}
        </SettingsSection>
      </div>
    </Page>
  );
}

/**
 * Route-level pending view (`/settings` prefetches the linked accounts): the same sections and
 * row shapes as skeletons, so the swap to real data does not shift the layout.
 */
export function SettingsPageSkeleton() {
  return (
    <Page width="md" eyebrow="Settings" title="Account">
      <output className="sr-only">Loading account settings</output>
      <div className="mt-12 space-y-10" aria-busy="true">
        <SettingsSection title="Profile">
          <RowSkeleton />
          <RowSkeleton />
        </SettingsSection>

        <SettingsSection title="Linked providers">
          <IconRowSkeleton />
          <IconRowSkeleton />
        </SettingsSection>

        <SettingsSection title="Passkeys">
          <IconRowSkeleton />
          <Skeleton className="mt-3 h-8 w-32" />
        </SettingsSection>

        <SettingsSection title="Danger zone">
          <Skeleton className="h-8 w-36" />
        </SettingsSection>
      </div>
    </Page>
  );
}

function SettingsSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-t border-border pt-6">
      <h2 className="font-mono text-xs tracking-caps text-muted-foreground uppercase">{title}</h2>
      <div className="mt-4 space-y-4">{children}</div>
    </section>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="truncate text-sm font-medium">{value}</span>
    </div>
  );
}

function RowSkeleton() {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1">
      <Skeleton className="h-5 w-16" />
      <Skeleton className="h-5 w-40" />
    </div>
  );
}

function IconRowSkeleton() {
  return (
    <div className="flex items-center gap-2">
      <Skeleton className="size-4" />
      <Skeleton className="h-5 w-24" />
    </div>
  );
}
