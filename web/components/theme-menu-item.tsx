"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useSyncExternalStore } from "react";

function subscribe() {
  return () => {};
}

/** True only once the client has taken over from SSR. `getServerSnapshot`
 *  (false) is what both the server render and React's own hydration-match pass
 *  use, so this can never itself cause a mismatch; React re-checks
 *  `getSnapshot` right after hydration and schedules the follow-up render on
 *  its own. Same helper as components/theme-toggle.tsx, deliberately duplicated
 *  rather than shared: it is six lines, and exporting it would make a hook out
 *  of something neither file should be importing from the other. */
function useHasMounted(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );
}

/** The theme control, as a row in the console's account menu.
 *
 *  WHY THIS EXISTS ALONGSIDE ThemeToggle. The header's toggle is a bare
 *  sun/moon circle sized for a floating nav bar, and the public site is the
 *  only place that renders it. The console has no such header — its only
 *  persistent chrome is the rail — so the control lives where the other
 *  account-level settings already are: next to the signed-in address, in the
 *  same <details> as "Connect repositories" and "Sign out".
 *
 *  IT SAYS WHAT IT WILL DO, NOT WHAT IS TRUE NOW. "Dark theme" beside a moon
 *  is ambiguous in a menu — it reads equally as a state label and as an
 *  action — and this is a <button> in a list of actions, so it is worded as
 *  one. The aria-label spells out the same thing for anyone who gets the row
 *  without its context.
 *
 *  `className` is passed in rather than imported. The rail owns MENU_ITEM, and
 *  reaching into components/dashboard-rail.tsx for it would drag that module's
 *  server-action imports into the client bundle — this is the one file in the
 *  menu that has a client boundary, so it is the one that must not. */
export function ThemeMenuItem({ className }: { className: string }) {
  const { resolvedTheme, setTheme } = useTheme();
  const mounted = useHasMounted();
  const isDark = mounted && resolvedTheme === "dark";
  const target = isDark ? "light" : "dark";

  return (
    <button
      type="button"
      onClick={() => setTheme(target)}
      aria-label={`Switch to ${target} theme`}
      /* The mount guard renders the light-mode wording for one commit, exactly
         as the header's toggle does. Here it costs nothing a person can see:
         this row lives inside a collapsed <details>, so on the load where the
         stale label exists the menu is shut. Opening it is a later interaction,
         by which time `mounted` is true. */
      className={`${className} flex items-center gap-2`}
    >
      {isDark ? (
        <Sun aria-hidden className="size-3.5 flex-none" />
      ) : (
        <Moon aria-hidden className="size-3.5 flex-none" />
      )}
      Switch to {target}
    </button>
  );
}
