"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";

/** Sun/moon toggle, matching the GitHub Pages site's toggle contract:
 *  binary light/dark, defaults to light, persisted by next-themes
 *  (localStorage under "theme"). resolvedTheme is undefined on the server
 *  and on the first client render alike — both render the light-mode
 *  icon, so there's nothing to gate on mount for. */
export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const isDark = resolvedTheme === "dark";

  return (
    <button
      type="button"
      onClick={() => setTheme(isDark ? "light" : "dark")}
      aria-label="Toggle color theme"
      aria-pressed={isDark}
      title={isDark ? "Switch to light theme" : "Switch to dark theme"}
      className="flex size-8 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
    >
      {isDark ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </button>
  );
}
