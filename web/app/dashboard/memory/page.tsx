import { withAuth } from "@workos-inc/authkit-nextjs";
import Link from "next/link";
import { redirect } from "next/navigation";

import { DashboardRail, SUBMIT_BUTTON, SWITCH_LABEL, SWITCH_SELECT } from "@/components/dashboard-rail";
import { StateChip } from "@/components/state-chip";
import { frontDoor } from "@/lib/dashboard-model";
import {
  matchedNothingGloss,
  normalizeQuery,
  parseStatusFilter,
  readsBeforeDiffLine,
  recordHref,
  selectRecords,
} from "@/lib/memory-model";
import { getConnections, getRepositoryDecisions, SessionApiError } from "@/lib/session-api";

/** The route chip, matching the ledger's; declared here for the reason the
 *  settings page gives. */
const ROUTE = "rounded-[3px] bg-accent px-[7px] py-0.5 text-[var(--iridescent)] tracking-[.06em]";

/** The decisions in one connected repository, as written, at HEAD.
 *
 *  WHAT THIS IS: the visible half of the record. The same read the intent
 *  tier makes before a review, shown to a person: id, title, status, date,
 *  the file, the body. A status filter, a search box, and one sentence
 *  about whether Doug reads these before it reads a diff for this
 *  installation. It is not a derived record and it claims no citation: those
 *  arrive with the store (ADR-0022), and the screen says so by not
 *  showing them.
 *
 *  WHAT IS NEVER GATED: the list. `intent.enabled_for` and the deep-read
 *  setting gate the model read at review time; this is a listing of files
 *  the installation already grants Doug. The sentence follows all three
 *  flags (deep read, the allowlist, the reader switch), and only the
 *  sentence does.
 *
 *  WHICH ZERO: the API says whether the walk matched nothing, and where it
 *  looked. That renders the `unknown` chip naming the directories, never a
 *  bare 0. A filter or a search that keeps nothing is a different sentence,
 *  because the records exist.
 */
export default async function MemoryPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { user, accessToken, organizationId } = await withAuth();
  if (!user || !accessToken) redirect("/sign-in");

  let connections: Awaited<ReturnType<typeof getConnections>> | null = null;
  try {
    connections = await getConnections(accessToken);
  } catch {
    connections = null;
  }
  if (connections === null) redirect("/dashboard");

  const door = frontDoor(connections.connections, organizationId);
  if (door.state !== "runs") redirect("/dashboard");
  const connection = door.current;

  const params = await searchParams;
  const repositories = [...connection.repositories].sort((a, b) =>
    a.full_name.localeCompare(b.full_name),
  );
  const requested = Number(Array.isArray(params.repo) ? params.repo[0] : params.repo);
  const repository = repositories.find((r) => r.id === requested) ?? repositories[0] ?? null;
  const status = parseStatusFilter(params.status);
  const query = normalizeQuery(params.q);

  let decisions: Awaited<ReturnType<typeof getRepositoryDecisions>> | null = null;
  let readFailure: string | null = null;
  if (repository) {
    try {
      decisions = await getRepositoryDecisions(accessToken, repository.id);
    } catch (error) {
      readFailure =
        error instanceof SessionApiError && error.status !== null
          ? `the read answered ${error.status}`
          : "the read did not answer";
    }
  }

  const shown = decisions ? selectRecords(decisions.items, status, query) : [];
  const line = decisions ? readsBeforeDiffLine(decisions.reads_before_diff) : null;

  return (
    <div className="dashboard-surface">
      <div className="grid min-h-screen grid-cols-1 lg:grid-cols-[212px_minmax(0,1fr)]">
        <DashboardRail
          connections={connections.connections}
          current={connection}
          userEmail={user.email}
          section="memory"
          runsHref="/dashboard"
          repositoriesHref="/dashboard?view=repositories"
        />

        <main className="mx-auto w-full max-w-[820px] px-6 py-10">
          <div className="mono mb-6 flex items-center gap-3 text-[10.5px] uppercase tracking-[.15em] text-[var(--dim)]">
            <span className={ROUTE}>/memory</span>
            <span className="truncate normal-case tracking-normal text-muted-foreground">
              {connection.account_login}
            </span>
            <span className="h-px flex-1 bg-border" />
          </div>

          <h1 className="font-heading text-[32px] font-semibold tracking-[-.03em]">Memory</h1>
          <p className="mt-3 max-w-[620px] text-sm text-muted-foreground">
            The decisions in your repository, as written. Read from the default branch each time,
            never typed in by hand. Commitment is the decision.
          </p>

          {repositories.length === 0 ? (
            <p className="mt-8 max-w-[620px] text-sm text-muted-foreground">
              This space has no repositories Doug can see yet. Add some to the installation from{" "}
              <Link href="/install/start" prefetch={false} className="text-foreground underline underline-offset-[3px]">
                Connect repositories
              </Link>
              , then come back.
            </p>
          ) : (
            <>
              <form method="GET" action="/dashboard/memory" className="mt-8 flex flex-wrap items-end gap-3">
                <label className="flex flex-col gap-1">
                  <span className={SWITCH_LABEL}>Repository</span>
                  <select name="repo" defaultValue={repository?.id} className={SWITCH_SELECT}>
                    {repositories.map((r) => (
                      <option key={r.id} value={r.id}>{r.full_name}</option>
                    ))}
                  </select>
                </label>
                <label className="flex flex-col gap-1">
                  <span className={SWITCH_LABEL}>Status</span>
                  <select name="status" defaultValue={status} className={SWITCH_SELECT}>
                    <option value="accepted">accepted</option>
                    <option value="all">all</option>
                  </select>
                </label>
                <label className="flex flex-col gap-1">
                  <span className={SWITCH_LABEL}>Search</span>
                  <input
                    type="search"
                    name="q"
                    defaultValue={query}
                    placeholder="id, title, or body"
                    className="mono h-[32px] w-[220px] rounded-[5px] border border-border bg-card px-2.5 text-[12.5px] text-foreground focus:border-[var(--iridescent)] focus:outline-2 focus:outline-offset-2 focus:outline-[color-mix(in_srgb,var(--iridescent)_35%,transparent)]"
                  />
                </label>
                <button type="submit" className={`${SUBMIT_BUTTON} h-[32px]`}>show</button>
              </form>

              {/* THE LINE. Rendered from the three flags and nothing else; the
                  list below never consults them. */}
              {line && (
                <p className="mt-6 text-sm text-muted-foreground">
                  {line.on ? (
                    <span>{line.detail}</span>
                  ) : (
                    <StateChip kind="off" subject="reads before the diff" detail={line.detail} />
                  )}
                </p>
              )}

              {readFailure && (
                <p className="mt-6 text-sm">
                  <StateChip kind="unknown" subject="decisions" detail={readFailure} />
                </p>
              )}

              {decisions && decisions.matched_nothing && (
                <p className="mt-6 text-sm">
                  <StateChip kind="unknown" subject="decisions" detail={matchedNothingGloss(decisions)} />
                </p>
              )}

              {decisions && !decisions.matched_nothing && (
                <>
                  <p className="mono mt-6 text-[11px] uppercase tracking-[.12em] text-[var(--dim)]">
                    {decisions.count_accepted} accepted of {decisions.items.length} on record
                    {decisions.directory ? ` in ${decisions.directory}` : ""}
                    {decisions.files_skipped > 0 ? `; ${decisions.files_skipped} file${decisions.files_skipped === 1 ? "" : "s"} skipped without frontmatter` : ""}
                  </p>
                  {shown.length === 0 ? (
                    <p className="mt-4 text-sm text-muted-foreground">
                      No record matches this filter. The records are there; widen the status or clear the search.
                    </p>
                  ) : (
                    <ul className="mt-4 flex list-none flex-col gap-0 border-t border-border p-0">
                      {shown.map((record) => (
                        <li key={record.ref} className="border-b border-border py-4">
                          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                            <span className="mono text-[11px] text-[var(--dim)]">{record.id}</span>
                            <h2 className="text-[15px] font-medium text-foreground">{record.title}</h2>
                            <span className="mono ml-auto text-[10px] uppercase tracking-[.12em] text-[var(--dim)]">
                              {record.status}{record.date ? ` · ${record.date}` : ""}
                            </span>
                          </div>
                          <details className="mt-2">
                            <summary className="mono cursor-pointer text-[11px] text-muted-foreground">
                              {record.ref}
                            </summary>
                            <pre className="mt-2 max-h-[420px] overflow-auto whitespace-pre-wrap rounded-[5px] border border-border bg-card p-3 text-[12px] text-foreground">
                              {record.body}
                            </pre>
                            <a
                              href={recordHref(decisions.full_name, record.ref)}
                              className="mono mt-2 inline-block text-[11px] text-foreground underline underline-offset-[3px]"
                            >
                              Open on GitHub at HEAD
                            </a>
                          </details>
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              )}
            </>
          )}
        </main>
      </div>
    </div>
  );
}
