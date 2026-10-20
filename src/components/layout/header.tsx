import { Link, useNavigate, useRouteContext, useRouter } from "@tanstack/react-router";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";

import { authClient } from "#/lib/auth-client";
import { Button } from "#/components/ui/button";
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
          tanstack-start
        </Link>

        <nav className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            render={
              <a
                href="https://github.com/zek01svg/tanstack-start-template"
                target="_blank"
                rel="noopener noreferrer"
                aria-label="GitHub repository"
              />
            }
          >
            GitHub
          </Button>
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
