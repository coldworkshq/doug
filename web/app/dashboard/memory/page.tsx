import Link from "next/link";

import { DashboardRail, ROUTE_CHIP, SUBMIT_BUTTON, SWITCH_LABEL, SWITCH_SELECT } from "@/components/dashboard-rail";
import { StateChip } from "@/components/state-chip";
import {
  fileAccounting,
  firstParam,
  matchedNothingGloss,
  parseStatusFilter,
  queryFromParams,
  readsBeforeDiffLine,
  recordHref,
  selectRecords,
} from "@/lib/memory-model";
import { getRepositoryDecisions } from "@/lib/session-api";
import { loadWorkspace, sortedRepositories } from "@/lib/workspace";

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
  const { user, accessToken, connections, connection } = await loadWorkspace();

  const params = await searchParams;
  const repositories = sortedRepositories(connection);
  // A bookmarked repository that is not in this space is said so, never
  // silently swapped for the first one under the bookmarked URL.
  const requestedRaw = firstParam(params.repo);
  const requested = requestedRaw === undefined ? null : Number(requestedRaw);
  const repository =
    requested === null
      ? (repositories[0] ?? null)
      : (repositories.find((r) => r.id === requested) ?? null);
  const repoNotFound = requested !== null && repository === null && repositories.length > 0;
  const status = parseStatusFilter(params.status);
  const query = queryFromParams(params.q);

  let decisions: Awaited<ReturnType<typeof getRepositoryDecisions>> | null = null;
  if (repository) {
    try {
      decisions = await getRepositoryDecisions(accessToken, repository.id);
    } catch {
      decisions = { ok: false, failure: { status: null, reason: "the read did not answer", reads_before_diff: null } };
    }
  }
  const loaded = decisions?.ok ? decisions.decisions : null;
  const readFailure = decisions && !decisions.ok ? decisions.failure.reason : null;
  // THE LINE. Rendered from the three flags and nothing else; the list below
  // never consults them. A broken read still carries the flags on its 502.
  const flags = decisions?.ok ? decisions.decisions.reads_before_diff : (decisions?.failure.reads_before_diff ?? null);
  const line = flags ? readsBeforeDiffLine(flags) : null;
  const shown = loaded ? selectRecords(loaded.items, status, query, loaded.binding_status) : [];

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
            <span className={ROUTE_CHIP}>/memory</span>
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
                  <select name="repo" defaultValue={repository?.id ?? repositories[0]?.id} className={SWITCH_SELECT}>
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

              {repoNotFound && (
                <p className="mt-6 text-sm">
                  <StateChip kind="unknown" subject="repository" detail={`repository ${requestedRaw} is not in this space; pick one above`} />
                </p>
              )}

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

              {loaded && loaded.matched_nothing && (
                <p className="mt-6 text-sm">
                  <StateChip kind="unknown" subject="decisions" detail={matchedNothingGloss(loaded)} />
                </p>
              )}

              {loaded && !loaded.matched_nothing && (
                <>
                  <p className="mono mt-6 text-[11px] uppercase tracking-[.12em] text-[var(--dim)]">
                    {loaded.count_accepted} {loaded.binding_status} of {loaded.items.length} on record
                    {loaded.directory ? ` in ${loaded.directory}` : ""}
                    {fileAccounting(loaded)}
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
                              href={recordHref(loaded.full_name, record.ref)}
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
