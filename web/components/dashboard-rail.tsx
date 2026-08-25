import Link from "next/link";

import { signOutAction } from "@/app/auth/actions";
import { switchConnectionAction } from "@/app/dashboard/actions";
import { AutoSubmitSelect } from "@/components/auto-submit-select";
import { DougLogo } from "@/components/doug-logo";
import { ThemeMenuItem } from "@/components/theme-menu-item";
import { NoJsSubmit } from "@/components/no-js-submit";
import type { RepositoryConnection } from "@/lib/session-api";

/** The one connection whose label is editorial rather than descriptive: it
 *  disambiguates a neighbouring product for someone CHOOSING between spaces,
 *  which is why it lives beside the picker and not on the settings page. */
const LEMA_LABEL = "Lema — separate product";

/** A bordered control that wraps a <select>. The focus ring is on the wrapper,
 *  not the select, because the label and its value read as one control — and
 *  it is not optional: this is what changes whose data you are looking at.
 *  Stacked label-over-value in the rail, where the column is 212px and a
 *  side-by-side label would leave the org name six characters wide. */
export const SWITCH_CONTROL =
  "mono flex w-full flex-col gap-[3px] rounded-[5px] border border-border bg-card px-2 py-[5px] " +
  "focus-within:border-[var(--iridescent)] focus-within:outline-2 focus-within:outline-offset-2 " +
  "focus-within:outline-[color-mix(in_srgb,var(--iridescent)_35%,transparent)]";

export const SWITCH_LABEL = "text-[9px] uppercase tracking-[.14em] text-[var(--dim)]";

export const SWITCH_SELECT =
  "w-full max-w-full border-0 bg-transparent text-[12px] text-foreground outline-0";

export const SUBMIT_BUTTON =
  "mono cursor-pointer rounded-[4px] border border-border bg-card px-2 py-[5px] text-[11px] " +
  "text-muted-foreground hover:border-[var(--iridescent)] hover:text-foreground " +
  "focus-visible:border-[var(--iridescent)] focus-visible:text-foreground";

/** One row of the settings menu — the connect link and the sign-out button
 *  share it so a <Link> and a <button type="submit"> render as one list.
 *
 *  Hoisted so each tag stays short and legible. The reachability pin in
 *  lib/dashboard-contract.test.mjs deliberately does NOT read this string — it
 *  pins the href and the label, so restyling can never fail an ordering
 *  guarantee. */
const MENU_ITEM =
  "mono block w-full cursor-pointer rounded-[3px] border-0 bg-transparent px-2 py-[7px] " +
  "text-left text-[11px] text-muted-foreground no-underline hover:bg-accent " +
  "hover:text-[var(--iridescent)] focus-visible:bg-accent focus-visible:outline-2 " +
  "focus-visible:-outline-offset-2 focus-visible:outline-[color-mix(in_srgb,var(--iridescent)_35%,transparent)]";

/** A rail entry. The current section is marked by a filled tick in the left
 *  gutter AND by weight and ink — three carriers, because the tick is 2px wide
 *  and the accent is the one colour on this page that is not allowed to mean
 *  anything about a verdict. */
const RAIL_ITEM =
  "mono relative flex items-center gap-2 border-l-2 border-transparent py-[7px] pr-2 pl-[13px] " +
  "text-[11px] uppercase tracking-[.09em] text-[var(--dim)] no-underline " +
  "hover:bg-[var(--row-hover)] hover:text-foreground " +
  "aria-[current]:border-l-[var(--iridescent)] aria-[current]:bg-accent " +
  "aria-[current]:font-semibold aria-[current]:text-foreground";

export function connectionLabel(connection: RepositoryConnection): string {
  const label = connection.account_login.toLowerCase() === "lemahq"
    ? LEMA_LABEL
    : connection.label;
  return label ? `${connection.account_login} · ${label}` : connection.account_login;
}

export function ScopePicker({
  connections,
  current,
}: {
  connections: RepositoryConnection[];
  current: RepositoryConnection | null;
}) {
  const ready = connections.filter(
    (connection) => connection.status === "ready" && connection.organization_id,
  );
  if (ready.length === 0) return null;
  return (
    <form action={switchConnectionAction} className="flex flex-col gap-1.5 max-lg:w-[200px]">
      <label className={SWITCH_CONTROL}>
        <span className={SWITCH_LABEL}>space</span>
        <AutoSubmitSelect
          name="organization_id"
          defaultValue={current?.organization_id ?? ""}
          aria-label="Connected space"
          className={SWITCH_SELECT}
        >
          {!current && <option value="" disabled>choose</option>}
          {ready.map((connection) => (
            <option key={connection.installation_id} value={connection.organization_id ?? ""}>
              {connectionLabel(connection)}
            </option>
          ))}
        </AutoSubmitSelect>
      </label>
      {/* Not deleted — rendered until the client proves it is not needed. It
          used to be wrapped in a script-absent element, which covered strictly
          less: that only renders when scripting is DISABLED, so it did nothing
          in the two cases that actually happen — the seconds before hydration,
          and a bundle that loaded and threw. In both, this form had no working
          control at all and an operator could not switch spaces (Doug PR 103,
          reader:js-dependency-regression). */}
      <NoJsSubmit className={`${SUBMIT_BUTTON} w-full`}>open</NoJsSubmit>
    </form>
  );
}

/** The signed-in shell's left column, on every /dashboard route.
 *
 *  EXTRACTED so /dashboard/settings can wear it too. It was inline on the
 *  ledger page and the settings page had none, which made settings feel like a
 *  different product rather than a section of this one — you left the nav to
 *  reach it and had no way back except a single "Ledger" link.
 *
 *  A COMPONENT, NOT A LAYOUT, and the choice is not stylistic. A
 *  `dashboard/layout.tsx` would have to fetch `connections` itself, which is a
 *  second API round-trip per render on a page that already reads it; it cannot
 *  see `searchParams`, so the repo filter could not live there; and marking the
 *  current section would need `usePathname`, a client boundary this shell is
 *  built to avoid. Passing the page's own data down costs one prop and keeps
 *  every read where it already was.
 *
 *  `filter` and `readout` are SLOTS because both are ledger concerns. The rail
 *  never learns what `params` is, so the runs page's search state cannot leak
 *  into the settings route through shared chrome.
 */
export function DashboardRail({
  connections,
  current,
  userEmail,
  section,
  runsHref,
  repositoriesHref,
  filter,
  readout,
}: {
  connections: RepositoryConnection[];
  current: RepositoryConnection | null;
  userEmail: string;
  /** Which entry is marked current. `settings` is a route rather than a view,
   *  so it is a third value here and not a third `?view=`. */
  section: "runs" | "repositories" | "settings";
  runsHref: string;
  repositoriesHref: string;
  filter?: React.ReactNode;
  readout?: React.ReactNode;
}) {
  return (
        <aside
          aria-label="Dashboard navigation"
          className="flex flex-col border-b border-border bg-card max-lg:flex-row max-lg:flex-wrap max-lg:items-center max-lg:gap-x-4 max-lg:gap-y-2 max-lg:px-4 max-lg:py-2.5 lg:sticky lg:top-0 lg:h-screen lg:self-start lg:overflow-y-auto lg:border-r lg:border-b-0"
        >
          <div className="border-b border-border px-4 py-3.5 max-lg:border-0 max-lg:p-0">
            <Link href="/" className="font-heading flex items-center gap-2 text-[15px] font-bold text-inherit no-underline">
              <DougLogo size={19} /> doug
              <span className="mono ml-0.5 rounded-[3px] bg-accent px-1.5 py-0.5 text-[8.5px] font-medium uppercase tracking-[.12em] text-[var(--iridescent)]">dashboard</span>
            </Link>
          </div>

          <div className="flex flex-col gap-2 border-b border-border px-4 py-3.5 max-lg:flex-row max-lg:items-start max-lg:border-0 max-lg:p-0">
            <ScopePicker connections={connections} current={current} />
            {/* Stacked, not side by side: a 212px rail minus a submit button
                leaves ~115px of select, and "all repositories" — the DEFAULT
                value — truncates inside it. A scope control whose current value
                cannot be read is one you have to open to learn the state of.

                A SLOT, not a fixture: this form narrows a ledger, and
                /dashboard/settings has no ledger to narrow. The rail renders
                whatever the page hands it and knows nothing about `params`,
                which is what lets the same rail serve both routes without
                dragging the runs page's search state into the settings one. */}
            {filter}
          </div>

          <nav className="flex flex-col border-b border-border py-1.5 max-lg:flex-row max-lg:border-0 max-lg:py-0" aria-label="Dashboard sections">
            {/* Both entries carry the current filters across, and both drop
                `page`: a page number is a position in one list and means
                nothing in the other. */}
            <Link
              href={runsHref}
              aria-current={section === "runs" ? "page" : undefined}
              className={RAIL_ITEM}
            >Runs</Link>
            <Link
              href={repositoriesHref}
              aria-current={section === "repositories" ? "page" : undefined}
              className={RAIL_ITEM}
            >Repositories</Link>
            {/* Still not built, and still said so. A nav entry that navigates
                nowhere is a lie about the product; one that names itself as
                unbuilt is a roadmap. */}
            <span className={RAIL_ITEM}>Evidence <small className="ml-auto text-[8px] tracking-normal normal-case">later</small></span>
            {/* Docs is a REAL destination and the only entry here that leaves
                the dashboard, so it sits below a rule rather than in the run of
                sections — and it takes no `aria-current`, because no /dashboard
                URL is ever the docs page. Grouping it with the two unbuilt
                placeholders would read as a fourth thing that might also be a
                promise; it is the one link on this list that works today. */}
            <Link href="/docs" className={`${RAIL_ITEM} mt-1.5 border-t border-t-border pt-[9px] max-lg:mt-0 max-lg:border-t-0 max-lg:pt-[7px]`}>Docs</Link>
          </nav>

          {readout}

          {/* THE ACCOUNT MENU is a <details>, not a popover.
              /dashboard is a server component and must stay one (RULING 2), and
              the things behind this gear are the ones that most need to work
              on an unhydrated page: signing out, connecting a repository, and
              reaching the settings that turn Doug down.
              The threshold gear can afford to be a Radix client leaf because a
              view control that does not load costs you a view; a sign-out that
              does not load strands you signed in. <details> is HTML, so the
              menu works before hydration, after a bundle throws, and with
              scripting off entirely.

              It opens UPWARD on the rail (it sits at the bottom of a full-height
              column) and downward in the narrow horizontal bar, where there is
              nothing above it. Clicking away does not close it — the honest cost
              of not reaching for JavaScript, and the gear toggles it back. */}
          {/* `relative` is on the ROW, not on the <details>. The rail is an
              overflow:auto container, so a panel that spills past it is clipped
              rather than shown — and anchored to the gear (a ~25px box at the
              right edge) a 196px panel hung 1px off the rail's left edge. Against
              the row's padding box, `inset-x-4` makes the panel exactly the
              rail's content width whatever that width becomes. */}
          {/* SETTINGS SITS AGAINST ACCOUNT, not in the run of sections above.
              It is not a view of the ledger — the two entries up there swap what
              the table shows and carry the filters across; this one leaves the
              table entirely — and it is the neighbour of the things it belongs
              with: who you are signed in as, and what Doug is allowed to do on
              your behalf. `mt-auto` moves here from the account row, so the two
              travel together as one block pinned to the bottom of the column.

              One entry, not two. It used to be in both the section list and the
              gear menu, which was defensible while they were far apart; six
              pixels from the gear, a second copy is just the same link twice. */}
          <div className="mt-auto max-lg:mt-0 max-lg:contents">
            <Link
              href="/dashboard/settings"
              aria-current={section === "settings" ? "page" : undefined}
              className={`${RAIL_ITEM} border-t border-t-border pt-[9px] max-lg:border-t-0 max-lg:pt-[7px]`}
            >Settings</Link>

          <div className="mono relative flex items-center gap-2 border-t border-border px-4 py-3 text-[10.5px] text-muted-foreground max-lg:mt-0 max-lg:border-0 max-lg:p-0">
            <span className="min-w-0 flex-1 truncate" title={userEmail}>{userEmail}</span>
            <details className="flex-none">
              <summary
                aria-label="Account"
                className="flex cursor-pointer list-none items-center rounded-[4px] border border-transparent p-1 text-muted-foreground hover:border-border hover:text-foreground focus-visible:border-[var(--iridescent)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color-mix(in_srgb,var(--iridescent)_35%,transparent)] [&::-webkit-details-marker]:hidden"
              >
                {/* The same cog the threshold gear draws, at the same weight —
                    two gears on one screen that were drawn differently would
                    read as two different kinds of control. */}
                <svg viewBox="0 0 16 16" aria-hidden className="size-[15px]" fill="none" stroke="currentColor" strokeWidth="1.4">
                  <circle cx="8" cy="8" r="2.1" />
                  <path d="M8 1.4v2M8 12.6v2M1.4 8h2M12.6 8h2M3.3 3.3l1.4 1.4M11.3 11.3l1.4 1.4M12.7 3.3l-1.4 1.4M4.7 11.3l-1.4 1.4" strokeLinecap="round" />
                </svg>
              </summary>
              <div className="absolute inset-x-4 bottom-[calc(100%+6px)] z-30 rounded-[5px] border border-border bg-card p-1 shadow-[0_10px_28px_-10px_rgba(0,0,0,.22)] max-lg:inset-x-auto max-lg:right-0 max-lg:top-[calc(100%+6px)] max-lg:bottom-auto max-lg:w-[196px]">
                <Link href="/install/start" prefetch={false} className={MENU_ITEM}>Connect repositories</Link>
                {/* Between the two, not beside the email itself: it is an
                    account-level preference like the others, and it is the
                    only one here that is reversible in a click, so it must not
                    sit where a mis-aimed pointer lands on "Sign out". */}
                <ThemeMenuItem className={MENU_ITEM} />
                <form action={signOutAction}><button type="submit" className={MENU_ITEM}>Sign out</button></form>
              </div>
            </details>
          </div>
          </div>
        </aside>
  );
}
