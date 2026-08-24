import { withAuth } from "@workos-inc/authkit-nextjs";
import Link from "next/link";
import { redirect } from "next/navigation";

import { FlagLineControl } from "@/components/flag-line-control";
import { PrCommentDenialBanner } from "@/components/pr-comment-denial-banner";
import { frontDoor } from "@/lib/dashboard-model";
import { getConnections } from "@/lib/session-api";

/** The route chip, matching the ledger's. Declared here rather than imported
 *  from the ledger page: `app/dashboard/page.tsx` is a route module, and
 *  importing presentation out of one route into another drags the whole module
 *  — its data reads included — into this page's graph. */
const ROUTE = "rounded-[3px] bg-accent px-[7px] py-0.5 text-[var(--iridescent)] tracking-[.06em]";

/** Every repository this installation covers, one block each.
 *
 *  WHY THIS PAGE EXISTS, given ADR-0013 put the flag line on the repositories
 *  table on purpose: the table's argument is adjacency — the line sits one
 *  column from the "needs you" count it decides, and reading them together is
 *  the point. That argument is about the LINE, and it is still true, so the
 *  table keeps its control. It says nothing about a person who has not opened
 *  the ledger, does not know the word "flag line", and is looking for the
 *  place where Doug is turned down. This page is that place. One API, two
 *  surfaces, one component (`FlagLineControl`) rendering both — see ADR-0013's
 *  amendment.
 *
 *  Deliberately NOT a rail-and-ledger shell. The ledger's chrome exists to
 *  keep a scope, a filter set and a selected run visible at once; this screen
 *  has one scope, no filters and nothing selected, and borrowing that shell
 *  would have been 200px of column holding a single link.
 */
export default async function SettingsPage() {
  const { user, accessToken, organizationId } = await withAuth();
  if (!user || !accessToken) redirect("/sign-in");

  let connections: Awaited<ReturnType<typeof getConnections>> | null = null;
  try {
    connections = await getConnections(accessToken);
  } catch {
    // Swallowed on purpose, and the redirect is OUTSIDE the catch because
    // `redirect` works by throwing. What the failure WAS still gets said —
    // just not twice. /dashboard already owns the three arms a failed
    // connections read can land on, each worded once and pinned in
    // lib/dashboard-contract.test.mjs, and a second copy here would be a
    // second thing to keep true.
    connections = null;
  }
  if (connections === null) redirect("/dashboard");

  const door = frontDoor(connections.connections, organizationId);
  // Same delegation, for the same reason: never-connected, expired scope and
  // "choose a space" are three different screens with three different next
  // actions, and all three already exist on the ledger. There is nothing to
  // set until one of them is resolved.
  if (door.state !== "runs") redirect("/dashboard");

  const connection = door.current;
  const defaults = connections.default_needs_you_threshold;
  // The installation's own list, not a rollup over the ledger: a repository
  // Doug has never reviewed still has settings worth changing, and it is the
  // one most likely to be why someone came here.
  const repositories = [...connection.repositories].sort((a, b) =>
    a.full_name.localeCompare(b.full_name),
  );

  return (
    <div className="dashboard-surface min-h-screen">
      <main className="mx-auto w-full max-w-[820px] px-6 py-10">
        <div className="mono mb-6 flex items-center gap-3 text-[10.5px] uppercase tracking-[.15em] text-[var(--dim)]">
          <span className={ROUTE}>/settings</span>
          <span className="truncate normal-case tracking-normal text-muted-foreground">
            {connection.account_login}
          </span>
          <span className="h-px flex-1 bg-border" />
          {/* The way back, and the only way to change space: switching spaces
              is the rail's picker, and a second picker here would be a second
              control writing the same session. */}
          <Link
            href="/dashboard"
            className="flex-none normal-case tracking-normal text-muted-foreground no-underline hover:text-foreground"
          >Ledger</Link>
        </div>

        <h1 className="font-heading text-[32px] font-semibold tracking-[-.03em]">Settings</h1>
        <p className="mt-3 max-w-[620px] text-sm text-muted-foreground">
          Per repository. Every setting here applies to reviews from now on — verdicts already
          recorded keep the line they were scored against, and an open pull request keeps its
          check until a new commit triggers a re-review.
        </p>

        {/* Read from the INSTALLATION, so it is stated once above the repositories
            it applies to rather than once per block. The API records the denial
            per installation, and repeating it beside forty toggles would read as
            forty faults. */}
        {connection.pr_comment_denied_at && (
          <div className="mt-6">
            <PrCommentDenialBanner deniedAt={connection.pr_comment_denied_at} />
          </div>
        )}

        {repositories.length === 0 ? (
          // Not an error, and not the never-connected screen either: the
          // installation is real and bound, it just covers nothing Doug can
          // see. The remedy is on GitHub, so the link goes there.
          <p className="mt-8 max-w-[620px] text-sm text-muted-foreground">
            This space has no repositories Doug can see yet. Add some to the installation from{" "}
            <Link href="/install/start" prefetch={false} className="text-foreground underline underline-offset-[3px]">
              Connect repositories
            </Link>
            , then come back.
          </p>
        ) : (
          <ul className="mt-8 flex list-none flex-col gap-0 border-t border-border p-0">
            {repositories.map((repository) => (
              <li key={repository.id} className="border-b border-border py-5">
                <h2 className="mono mb-2.5 text-[13px] font-medium text-foreground">
                  {repository.full_name}
                </h2>
                <FlagLineControl
                  layout="page"
                  githubRepoId={repository.id}
                  value={repository.needs_you_threshold}
                  prComment={repository.pr_comment}
                  deepRead={repository.deep_read}
                  defaults={defaults}
                />
              </li>
            ))}
          </ul>
        )}
      </main>
    </div>
  );
}
