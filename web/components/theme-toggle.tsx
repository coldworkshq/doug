"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useSyncExternalStore } from "react";

function subscribe() {
  return () => {};
}

/** True only once the client has taken over from SSR. `getServerSnapshot`
 *  (false) is what both the server render and React's own hydration-match
 *  pass use, so this can never itself cause a mismatch; React re-checks
 *  `getSnapshot` right after hydration completes and schedules the
 *  follow-up render on its own — no manual setState-in-effect needed. */
function useHasMounted(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );
}

/** Sun/moon toggle, matching the GitHub Pages site's toggle contract:
 *  binary light/dark, defaults to light, persisted by next-themes
 *  (localStorage under "theme").
 *
 *  The mount guard above is load-bearing, not decorative. A returning
 *  visitor who previously chose dark loads a page whose SERVER render has
 *  no localStorage access and so is always light (`defaultTheme="light"`
 *  in ThemeProvider) — but next-themes resolves `resolvedTheme` to "dark"
 *  from the very first client render, before this component would
 *  otherwise know to wait. `<html>` is protected from the resulting
 *  mismatch by `suppressHydrationWarning` in layout.tsx; this button is
 *  not, and React logs a real hydration error and discards/regenerates
 *  the tree. Rendering the light icon until mounted matches the server
 *  unconditionally, then swaps to the real theme one commit later — an
 *  intentional flash-of-stale-icon, smaller than a hydration error on
 *  every fresh load for every dark-mode visitor. Now that the header
 *  floats across every public route (/, /docs/*), that is the common
 *  case, not an edge one. */
export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const mounted = useHasMounted();
  const isDark = mounted && resolvedTheme === "dark";

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
