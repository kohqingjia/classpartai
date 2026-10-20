import type { ReactNode } from "react";
import { cn } from "#/lib/utils";

const WIDTHS = {
  sm: "max-w-sm",
  md: "max-w-2xl",
  lg: "max-w-4xl",
} as const;

interface PageProps {
  children: ReactNode;
  eyebrow?: string;
  title?: ReactNode;
  description?: ReactNode;
  width?: keyof typeof WIDTHS;
  className?: string;
}

export function Page({
  children,
  eyebrow,
  title,
  description,
  width = "lg",
  className,
}: PageProps) {
  return (
    <main className={cn("mx-auto w-full px-6 py-16", WIDTHS[width], className)}>
      {(eyebrow || title || description) && (
        <header>
          {eyebrow && (
            <p className="font-mono text-xs tracking-caps text-muted-foreground uppercase">
              {eyebrow}
            </p>
          )}
          {title && (
            <h1 className="font-heading mt-3 text-3xl font-semibold tracking-tight md:text-4xl">
              {title}
            </h1>
          )}
          {description && <p className="mt-3 max-w-xl text-muted-foreground">{description}</p>}
        </header>
      )}
      {children}
    </main>
  );
}
