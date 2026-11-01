import { Link, useNavigate, useRouteContext, useRouter } from "@tanstack/react-router";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";

import { authClient } from "#/lib/auth-client";
import { Button, buttonVariants } from "#/components/ui/button";
import { ThemeToggle } from "#/components/ui/theme-toggle";

export function Header() {
  // Resolved in `__root.tsx` beforeLoad, so the signed-in nav is in the server markup.
  const { user } = useRouteContext({ from: "__root__" });
  const navigate = useNavigate();
  const router = useRouter();
  const signOut = useMutation({
    mutationFn: async () => {
      const { error } = await authClient.signOut();
      if (error) throw new Error(error.message ?? "Failed to sign out");
    },
    onSuccess: async () => {
      await navigate({ to: "/" });
      await router.invalidate();
    },
    onError: error => toast.error(error.message),
  });

  return (
    <header className="sticky top-0 z-50 border-b border-border bg-background">
      <div className="mx-auto flex h-14 max-w-4xl items-center justify-between px-6">
        <Link
          to="/"
          className="font-mono text-sm font-medium tracking-tight transition-opacity hover:opacity-60"
        >
          ClassPart AI
        </Link>

        <nav aria-label="Main navigation" className="flex items-center gap-1">
          <Link to="/dashboard" className={buttonVariants({ variant: "ghost", size: "sm" })}>
            Workspace
          </Link>
          {user ? (
            <Link to="/settings" className={buttonVariants({ variant: "ghost", size: "sm" })}>
              Settings
            </Link>
          ) : (
            <Link to="/login" className={buttonVariants({ variant: "ghost", size: "sm" })}>
              Sign in
            </Link>
          )}
          {user && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={signOut.isPending}
              onClick={() => signOut.mutate()}
            >
              Sign out
            </Button>
          )}
          <ThemeToggle />
        </nav>
      </div>
    </header>
  );
}
