import * as React from "react";
import { Moon, Sun } from "lucide-react";

import { useTheme } from "#/components/providers/theme-provider";

import { Button } from "#/components/ui/button";

const emptySubscribe = () => () => {};

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const mounted = React.useSyncExternalStore(
    emptySubscribe,
    () => true,
    () => false
  );

  if (!mounted) {
    return <div aria-hidden="true" className="h-8 w-[68px]" />;
  }

  const themes = [
    { id: "light", icon: Sun, label: "Light" },
    { id: "dark", icon: Moon, label: "Dark" },
  ] as const;

  return (
    <div className="flex items-center gap-1">
      {themes.map(t => {
        const Icon = t.icon;
        const isActive = theme === t.id;

        return (
          <Button
            key={t.id}
            type="button"
            variant={isActive ? "default" : "ghost"}
            size="icon-sm"
            onClick={() => setTheme(t.id)}
            aria-label={`${t.label} theme`}
            aria-pressed={isActive}
            title={t.label}
          >
            <Icon className="size-3.5" />
          </Button>
        );
      })}
    </div>
  );
}
