import type { PropsWithChildren } from "react";
import { ThemeProvider as NextThemesProvider, useTheme } from "next-themes";
import type { ThemeProviderProps as NextThemesProviderProps } from "next-themes";

export type Theme = "dark" | "light" | "system";
export { useTheme };

type ThemeProviderProps = PropsWithChildren<
  Pick<
    NextThemesProviderProps,
    | "attribute"
    | "defaultTheme"
    | "disableTransitionOnChange"
    | "enableColorScheme"
    | "enableSystem"
    | "forcedTheme"
    | "nonce"
    | "scriptProps"
    | "storageKey"
    | "themes"
    | "value"
  >
>;

export function ThemeProvider({
  children,
  attribute = "class",
  defaultTheme = "light",
  storageKey = "template-theme",
  enableColorScheme = true,
  enableSystem = true,
  ...props
}: ThemeProviderProps) {
  return (
    <NextThemesProvider
      attribute={attribute}
      defaultTheme={defaultTheme}
      storageKey={storageKey}
      enableColorScheme={enableColorScheme}
      enableSystem={enableSystem}
      {...props}
    >
      {children}
    </NextThemesProvider>
  );
}
