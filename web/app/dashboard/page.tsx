import { withAuth } from "@workos-inc/authkit-nextjs";
import Link from "next/link";
import { redirect } from "next/navigation";

import { signOutAction } from "@/app/auth/actions";
import { BandChip } from "@/components/band-chip";
import { CoverageRuler } from "@/components/coverage-ruler";
import { DougLogo } from "@/components/doug-logo";
import { RunSpine } from "@/components/run-spine";
import {
  capSuffix,
  coverageView,
  dashboardFilters,
  filterRuns,
  outcomeTone,
  repositoryOptions,
} from "@/lib/dashboard-model";
import { outcomeLabel, outcomeToneClass, relativeAge } from "@/lib/runs-time";
import {
  getConnections,
  getSessionRun,
  getSessionRuns,
  type RepositoryConnection,
  type RunDetail,
  type RunSummary,
} from "@/lib/session-api";

import { finishSetupAction, switchConnectionAction } from "./actions";

const LEMA_LABEL = "Lema — separate product";

/** The reference canvas width the whole design was measured at. Every band
 *  that spans the viewport centres its content on it, which is why it repeats
 *  rather than living on one outer wrapper: the header's and the tab strip's
 *  hairlines run edge to edge while their contents stop here. */
const CANVAS = "mx-auto w-full max-w-[1440px]";

/** A bordered control that wraps a <select>. The focus ring is on the wrapper,
 *  not the select, because the label and its value read as one control — and
 *  it is not optional: this is what changes whose data you are looking at. */
const SWITCH_CONTROL =
  "mono flex min-h-[30px] items-center gap-[7px] rounded-[5px] border border-border bg-card px-2 py-1 " +
  "focus-within:border-[var(--iridescent)] focus-within:outline-2 focus-within:outline-offset-2 " +
  "focus-within:outline-[color-mix(in_srgb,var(--iridescent)_35%,transparent)]";

const SWITCH_LABEL = "text-[9px] uppercase tracking-[.11em] text-muted-foreground";

const SWITCH_SELECT =
  "max-w-[270px] max-[900px]:max-w-[180px] border-0 bg-transparent text-[11px] text-foreground outline-0";

const SUBMIT_BUTTON =
  "mono cursor-pointer rounded-[4px] border border-border bg-card px-2 py-[5px] text-[10px] " +
  "text-muted-foreground hover:border-[var(--iridescent)] hover:text-foreground " +
  "focus-visible:border-[var(--iridescent)] focus-visible:text-foreground";

/** Hoisted so the link's own tag stays short and legible. The reachability
 *  pin in lib/dashboard-contract.test.mjs deliberately does NOT read this
 *  string — it pins the href and the label, so restyling the link can never
 *  fail an ordering guarantee. */
const CONNECT_LINK =
  "mono text-[10px] text-[var(--iridescent)] underline underline-offset-[3px] max-[900px]:ml-auto " +
  "focus-visible:outline-2 focus-visible:outline-offset-[3px] " +
  "focus-visible:outline-[color-mix(in_srgb,var(--iridescent)_35%,transparent)]";

const TAB =
  "mono -mb-px border-b-2 border-transparent px-[13px] pt-[9px] pb-2 text-[10px] uppercase " +
  "tracking-[.08em] text-[var(--dim)] no-underline aria-[current]:border-b-[var(--iridescent)] " +
  "aria-[current]:font-semibold aria-[current]:text-foreground";

/** The evidence pane's section headings. The `<span>` inside each one is a
 *  provenance sub-label, styled here rather than at the call site so the
 *  headings' own markup stays the plain sentence it claims to be. */
const BLOCK_HEADING =
  "mono mb-3 flex items-center gap-2.5 text-[10px] font-medium uppercase tracking-[.16em] " +
  "text-muted-foreground [&_span]:text-[8px] [&_span]:normal-case [&_span]:tracking-[.04em] " +
  "[&_span]:text-[var(--dim)]";

const BLOCK = "border-b border-border py-[22px]";

/** The route chip — a monospace breadcrumb in the accent wash. */
const ROUTE = "rounded-[3px] bg-accent px-[7px] py-0.5 text-[var(--iridescent)] tracking-[.06em]";

const EMPTY_PAGE = "mx-auto max-w-[760px] px-6 py-[110px]";
const EMPTY_HEADING =
  "font-heading mt-[18px] text-[clamp(36px,7vw,64px)] font-semibold tracking-[-.05em]";
const EMPTY_BODY = "mt-4 max-w-[620px] text-base text-muted-foreground";

const EMPTY_NOTE = "text-xs text-muted-foreground";

/** A finding or a deviation: the marker column, then the rule and its words. */
const FINDING = "grid grid-cols-[62px_minmax(0,1fr)] gap-3 border-t border-[var(--rule-soft)] py-[11px]";

type DashboardParams = Record<string, string | string[] | undefined>;

function value(params: DashboardParams, key: string): string | undefined {
  const found = params[key];
  return Array.isArray(found) ? found[0] : found;
}

function href(params: DashboardParams, changes: Record<string, string | null>): string {
  const next = new URLSearchParams();
  for (const [key, raw] of Object.entries(params)) {
    const item = Array.isArray(raw) ? raw[0] : raw;
    if (item) next.set(key, item);
  }
  for (const [key, item] of Object.entries(changes)) {
    if (item === null) next.delete(key);
    else next.set(key, item);
  }
  const query = next.toString();
  return query ? `/dashboard?${query}` : "/dashboard";
}

function connectionLabel(connection: RepositoryConnection): string {
  const label = connection.account_login.toLowerCase() === "lemahq"
    ? LEMA_LABEL
    : connection.label;
  return label ? `${connection.account_login} · ${label}` : connection.account_login;
}

function ScopePicker({
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
    <form action={switchConnectionAction} className="flex items-center gap-1.5">
      <label className={SWITCH_CONTROL}>
        <span className={SWITCH_LABEL}>space</span>
        <select
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
        </select>
      </label>
      <button type="submit" className={SUBMIT_BUTTON}>open</button>
    </form>
  );
}

function PendingConnections({ connections }: { connections: RepositoryConnection[] }) {
  const pending = connections.filter(
    (connection) => connection.status === "setup_required",
  );
  if (pending.length === 0) return null;
  return (
    <section
      className="mono mx-auto grid w-full max-w-[1400px] grid-cols-[210px_minmax(0,1fr)] gap-[18px] border-b border-border bg-background/[.91] px-5 py-2.5 max-[900px]:grid-cols-1"
      aria-labelledby="pending-connections-title"
    >
      <div className="flex flex-col justify-center gap-[3px]">
        <span id="pending-connections-title" className="text-[9px] uppercase tracking-[.12em] text-[var(--iridescent)]">setup required</span>
        <small className="text-[9px] leading-[1.35] text-muted-foreground">Finish binding these installations before opening their run ledger.</small>
      </div>
      <div className="flex flex-col">
        {pending.map((connection) => (
          <div
            className="flex min-h-[38px] items-center justify-between gap-4 border-t border-[var(--rule-soft)] py-[5px] first:border-t-0"
            key={connection.installation_id}
          >
            <span className="flex min-w-0 flex-col gap-0.5">
              <strong className="truncate text-[10px] font-medium">{connectionLabel(connection)}</strong>
              <small className="text-[9px] text-muted-foreground">{connection.account_type.toLowerCase()} · {connection.repositories.length} repositories</small>
            </span>
            <form action={finishSetupAction}>
              <input type="hidden" name="installation_id" value={connection.installation_id} />
              <button
                type="submit"
                className="cursor-pointer rounded-[3px] border border-[var(--iridescent)] bg-transparent px-2 py-[5px] text-[9px] uppercase text-[var(--iridescent)] hover:bg-accent focus-visible:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color-mix(in_srgb,var(--iridescent)_30%,transparent)]"
              >finish setup</button>
            </form>
          </div>
        ))}
      </div>
    </section>
  );
}

function FilterChip({
  active,
  children,
  target,
}: {
  active: boolean;
  children: React.ReactNode;
  target: string;
}) {
  return (
    <Link
      className="mono rounded-[4px] border border-border bg-card px-[9px] py-1 text-[11px] text-muted-foreground no-underline hover:border-[var(--iridescent)] hover:text-foreground [&[data-active]]:border-foreground [&[data-active]]:bg-foreground [&[data-active]]:text-background"
      data-active={active || undefined}
      href={target}
    >{children}</Link>
  );
}

/** The read column's miniature of the forensic ruler. Coverage is a magnitude:
 *  it renders on globals' neutral sequential ramp (.cov-track / .cov-fill) and
 *  never on --flag or --clear. Low coverage is alarmed by how empty the track
 *  looks, not by hue — the same rule CoverageRuler's cut marker follows. */
function CoverageCell({ run }: { run: RunSummary }) {
  const view = coverageView(run);
  if (view.kind === "no-read") return <span className="mono text-[10px] text-muted-foreground">no read</span>;
  return (
    <div className="mono flex items-center gap-[7px] text-[10px] text-foreground" title={view.chars ?? undefined}>
      <span className="cov-track block h-1.5 w-[62px]">
        <span className="cov-fill block h-full" style={{ width: `${view.percent ?? 0}%` }} />
      </span>
      <span>{view.label}</span>
    </div>
  );
}

/** Column widths are the console's, not the deleted module's. They travel with
 *  the cell components this table now renders: band is 112px because BandChip's
 *  "needs you" wrapped to two lines at 96 and dragged every flagged row taller
 *  than its neighbours. */
const COLUMNS: Array<{ label: string; cls: string }> = [
  { label: "score", cls: "w-[78px] text-right" },
  { label: "pull request", cls: "" },
  { label: "band", cls: "w-[112px]" },
  { label: "tier", cls: "w-[88px]" },
  { label: "read", cls: "w-[176px]" },
  { label: "outcome", cls: "w-[104px]" },
  { label: "job", cls: "w-[118px]" },
  { label: "age", cls: "w-[54px] text-right" },
];

function RunTable({ rows, params }: { rows: RunSummary[]; params: DashboardParams }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[980px] table-fixed border-collapse">
        <thead>
          <tr>
            {COLUMNS.map((column) => (
              <th
                key={column.label}
                className={`mono border-b border-border px-2.5 pb-[7px] text-left text-[10px] font-medium uppercase tracking-[.13em] text-muted-foreground ${column.cls}`}
              >
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((run) => (
            <tr key={run.verdict_id} className="border-b border-[var(--rule-soft)] hover:bg-[var(--row-hover)]">
              <td className="h-[34px] px-2.5 text-right align-middle">
                <span className={"mono text-[14.5px] font-semibold " + (run.band === "flagged" ? "data-flag" : "data-clear")}>
                  {run.score.toFixed(2)}
                </span>
              </td>
              <td className="h-[34px] min-w-0 px-2.5 align-middle">
                <Link
                  className="flex min-w-0 items-baseline gap-2 text-inherit no-underline"
                  href={href(params, { run: String(run.verdict_id) })}
                >
                  <span className="mono flex-none text-[10px] text-muted-foreground"><b className="font-medium text-foreground">{run.repo}</b> #{run.pr_number}</span>
                  <strong className="min-w-0 flex-1 truncate text-xs font-normal">{run.title}</strong>
                </Link>
              </td>
              <td className="h-[34px] px-2.5 align-middle"><BandChip band={run.band} /></td>
              <td className="mono h-[34px] px-2.5 align-middle text-[10px] text-muted-foreground">{run.tier}</td>
              <td className="h-[34px] px-2.5 align-middle"><CoverageCell run={run} /></td>
              <td className="mono h-[34px] px-2.5 align-middle text-xs">
                <span className={outcomeToneClass(outcomeTone(run.outcome_14))}>{outcomeLabel(run.outcome_14)}</span>
              </td>
              <td className={"mono h-[34px] px-2.5 align-middle text-[10px] " + (run.job?.error ? "data-flag" : "text-muted-foreground")}>
                {run.job?.error ? `${run.job.attempts}× · ${run.job.error}` : (run.job?.status ?? "—")}
              </td>
              <td className="mono h-[34px] px-2.5 text-right align-middle text-[10px] text-muted-foreground">{relativeAge(run.scored_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && <p className="mono border-b border-border px-2.5 py-9 text-muted-foreground">No runs match these filters.</p>}
    </div>
  );
}

function Evidence({ detail, summary }: { detail: RunDetail; summary: RunSummary }) {
  return (
    <section className={`${CANVAS} px-5 pt-[18px] pb-12`} aria-labelledby="run-evidence-title">
      <header className="flex items-end justify-between gap-6 border-t border-border pt-4 pb-[22px] max-[900px]:flex-col max-[900px]:items-start">
        <div>
          <p className="mono mb-[7px] text-[10px] text-muted-foreground">/runs/{detail.verdict_id} · {detail.repo} · #{detail.pr_number}</p>
          <h2 id="run-evidence-title" className="font-heading max-w-[980px] text-[clamp(22px,2.2vw,30px)] font-semibold leading-[1.1] tracking-[-.035em]">{summary.title}</h2>
        </div>
        <div className="mono flex flex-none flex-col items-end max-[900px]:items-start">
          <strong className={"text-[36px] font-medium " + (detail.band === "flagged" ? "data-flag" : "data-clear")}>
            {detail.score.toFixed(2)}
          </strong>
          <span className="text-[9px] text-muted-foreground">{detail.band === "flagged" ? "needs you" : "cleared"} · threshold {detail.threshold.toFixed(2)}</span>
        </div>
      </header>

      <div className="grid grid-cols-1 border-t border-border lg:grid-cols-[230px_minmax(0,1fr)]">
        <RunSpine run={detail} />

        <div className="min-w-0 lg:pl-6">
          <section className={BLOCK}>
            <h3 className={BLOCK_HEADING}>What the reader was given <span>reader evidence</span></h3>
            {detail.coverage ? (
              // changed_files comes off the summary row, the same denominator
              // the read column above used for this run — one number, so the
              // table and the pane can never print two different rates for it.
              <CoverageRuler
                coverage={detail.coverage}
                changedFiles={summary.changed_files}
                filesDropped={detail.pr?.files_dropped ?? []}
              />
            ) : <p className={EMPTY_NOTE}>No reader coverage was recorded for this run.</p>}
          </section>

          <section className={BLOCK}>
            <h3 className={BLOCK_HEADING}>The read</h3>
            <dl className="mono grid grid-cols-[130px_1fr] gap-x-[18px] gap-y-2 text-[10px]">
              <dt className="uppercase text-muted-foreground">tier</dt><dd className="m-0 whitespace-pre-wrap">{detail.tier}</dd>
              <dt className="uppercase text-muted-foreground">model</dt><dd className="m-0 whitespace-pre-wrap">{detail.model ?? "not recorded"}</dd>
              <dt className="uppercase text-muted-foreground">prompt hash</dt><dd className="m-0 whitespace-pre-wrap">{detail.prompt_hash ?? "not stamped"}</dd>
              <dt className="uppercase text-muted-foreground">risk score</dt><dd className="m-0 whitespace-pre-wrap">{detail.risk_score ?? "not recorded"}</dd>
              <dt className="uppercase text-muted-foreground">head sha</dt><dd className="m-0 whitespace-pre-wrap">{detail.head_sha ?? "not recorded"}</dd>
              <dt className="uppercase text-muted-foreground">rationale</dt><dd className="m-0 whitespace-pre-wrap">{detail.rationale ?? "No rationale was recorded."}</dd>
            </dl>
          </section>

          <section className={BLOCK}>
            <h3 className={BLOCK_HEADING}>Findings <span>{detail.reasons.length}</span></h3>
            {detail.reasons.map((reason) => (
              <div className={FINDING} key={`${reason.rule}-${reason.label}`}>
                <span className="mono data-flag text-[9px] uppercase">{reason.severity ?? "rule"}</span>
                <div><code className="mono text-[10px]">{reason.rule}</code><p className="mt-[3px] text-xs text-muted-foreground">{reason.label}</p></div>
              </div>
            ))}
            {detail.reasons.length === 0 && <p className={EMPTY_NOTE}>No findings recorded.</p>}
          </section>

          <section className={BLOCK}>
            <h3 className={BLOCK_HEADING}>Deviations <span>separate stream</span></h3>
            {detail.deviations.map((deviation) => (
              <div className={FINDING} key={`${deviation.type}-${deviation.description}`}>
                <span className="mono data-flag text-[9px] uppercase">{deviation.severity}</span>
                <div><code className="mono text-[10px]">{deviation.type}</code><p className="mt-[3px] text-xs text-muted-foreground">{deviation.description}</p></div>
              </div>
            ))}
            {detail.deviations.length === 0 && <p className={EMPTY_NOTE}>No deviations recorded.</p>}
          </section>

          <section className={BLOCK}>
            <h3 className={BLOCK_HEADING}>Outcome</h3>
            <div className="grid grid-cols-[repeat(auto-fit,minmax(190px,1fr))] gap-2.5">
              {detail.outcomes.map((outcome) => (
                <div key={`${outcome.window_days}-${outcome.observed_at}`} className="flex flex-col border border-border bg-card p-3">
                  <span className="mono text-[9px] text-muted-foreground">{outcome.window_days ?? "?"}-day window</span>
                  {/* Tone and word both come from the shared rule, so this tile
                      and the outcome column above cannot describe the same row
                      differently — and neither can the console, which renders
                      through the very same two functions. */}
                  <strong className={"mono my-1 text-[15px] " + outcomeToneClass(outcomeTone(outcome.kind))}>{outcomeLabel(outcome.kind)}</strong>
                  <small className="mono text-[9px] text-muted-foreground">observed {new Date(outcome.observed_at).toLocaleDateString()}</small>
                </div>
              ))}
              {detail.outcomes.length === 0 && <p className={EMPTY_NOTE}>No outcome recorded yet.</p>}
            </div>
          </section>
        </div>
      </div>
    </section>
  );
}

function NoConnection({ userLabel }: { userLabel: string }) {
  return (
    <main className={EMPTY_PAGE}>
      <p className={`mono inline-block text-[10px] uppercase ${ROUTE}`}>/account</p>
      <h1 className={EMPTY_HEADING}>{userLabel}, you&apos;re in.</h1>
      <p className={EMPTY_BODY}>{"You're in. Connect GitHub only when you want Doug to review repositories."}</p>
      <Link
        href="/install/start"
        prefetch={false}
        className="mono mt-[26px] inline-block rounded-[4px] bg-foreground px-3.5 py-2.5 text-[11px] text-background no-underline"
      >Connect GitHub</Link>
    </main>
  );
}

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: Promise<DashboardParams>;
}) {
  const params = await searchParams;
  const auth = await withAuth();
  const { user, accessToken, organizationId } = auth;
  if (!user || !accessToken) redirect("/sign-in");
  const { connections } = await getConnections(accessToken);
  const current = connections.find(
    (connection) => connection.organization_id === organizationId && connection.status === "ready",
  ) ?? null;
  const userLabel = user.firstName || user.email || "You";

  let rows: RunSummary[] = [];
  let capNote = "";
  let selectedSummary: RunSummary | null = null;
  let detail: RunDetail | null = null;
  const filters = dashboardFilters(params);
  if (current) {
    const response = await getSessionRuns(accessToken, filters.repo);
    rows = filterRuns(response.items, filters);
    capNote = capSuffix(response.items.length, response.limit);
    const selectedId = Number(value(params, "run"));
    selectedSummary = Number.isInteger(selectedId)
      ? response.items.find((run) => run.verdict_id === selectedId) ?? null
      : null;
    if (selectedSummary) detail = await getSessionRun(accessToken, selectedSummary.verdict_id);
  }

  return (
    <div className="dashboard-surface">
      <header className={`${CANVAS} sticky top-0 z-20 flex min-h-[52px] items-center gap-[18px] border-b border-border bg-background/[.88] px-5 py-2 backdrop-blur-[10px] max-[900px]:static max-[900px]:flex-wrap max-[900px]:items-start`}>
        <Link href="/" className="font-heading flex items-center gap-2 text-base font-bold text-inherit no-underline">
          <DougLogo size={20} /> doug <span className="mono ml-0.5 rounded-[3px] bg-accent px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-[.12em] text-[var(--iridescent)]">dashboard</span>
        </Link>
        <ScopePicker connections={connections} current={current} />
        {current && <form method="GET" className="flex items-center gap-1.5">
          <label className={SWITCH_CONTROL}>
            <span className={SWITCH_LABEL}>repo</span>
            <select name="repo" defaultValue={filters.repo} aria-label="Repository" className={SWITCH_SELECT}>
              {repositoryOptions(current).map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>
          <button type="submit" className={SUBMIT_BUTTON}>filter</button>
        </form>}
        <Link href="/install/start" prefetch={false} className={CONNECT_LINK}>Connect repositories</Link>
        <div className="mono ml-auto flex items-center gap-2.5 text-[10px] text-muted-foreground max-[900px]:ml-0 max-[900px]:w-full max-[900px]:justify-end">
          <span>{user.email}</span>
          <form action={signOutAction}><button type="submit" className="cursor-pointer border-0 bg-transparent text-inherit underline">sign out</button></form>
        </div>
      </header>
      <nav className={`${CANVAS} flex gap-0.5 border-b border-border bg-background px-5`} aria-label="Dashboard sections">
        <Link href="/dashboard" aria-current="page" className={TAB}>Runs</Link>
        <span className={TAB}>Repositories <small className="text-[8px]">later</small></span>
        <span className={TAB}>Evidence <small className="text-[8px]">later</small></span>
      </nav>
      <PendingConnections connections={connections} />

      {connections.length === 0 ? <NoConnection userLabel={userLabel} /> : !current ? (
        <main className={EMPTY_PAGE}>
          <p className={`mono inline-block text-[10px] uppercase ${ROUTE}`}>/spaces</p>
          <h1 className={EMPTY_HEADING}>Choose a connected space.</h1>
          <p className={EMPTY_BODY}>Each space stays separate. Runs from one installation never join another.</p>
          <div className="mt-7"><ScopePicker connections={connections} current={null} /></div>
        </main>
      ) : (
        <main>
          <div className={`mono ${CANVAS} flex items-center gap-3 px-5 pt-[26px] pb-3 text-[10px] uppercase tracking-[.15em] text-muted-foreground`}>
            <span className={ROUTE}>/runs</span> Verdict history for {connectionLabel(current)}
            <span className="h-px flex-1 bg-border" />
          </div>
          <section className={`${CANVAS} px-5 pb-6`}>
            <div className="flex flex-wrap items-center gap-[7px] pt-3 pb-[11px]">
              <FilterChip active={filters.band === "all" && filters.tier === "all" && !filters.lowCoverage && !filters.hasError} target={href(params, { band: null, tier: null, coverage: null, error: null })}>all</FilterChip>
              <FilterChip active={filters.band === "flagged"} target={href(params, { band: filters.band === "flagged" ? null : "flagged" })}>needs you</FilterChip>
              <FilterChip active={filters.band === "cleared"} target={href(params, { band: filters.band === "cleared" ? null : "cleared" })}>cleared</FilterChip>
              <FilterChip active={filters.tier === "reader"} target={href(params, { tier: filters.tier === "reader" ? null : "reader" })}>reader</FilterChip>
              <FilterChip active={filters.tier === "deterministic"} target={href(params, { tier: filters.tier === "deterministic" ? null : "deterministic" })}>deterministic</FilterChip>
              <FilterChip active={filters.lowCoverage} target={href(params, { coverage: filters.lowCoverage ? null : "low" })}>coverage &lt; 50%</FilterChip>
              <FilterChip active={filters.hasError} target={href(params, { error: filters.hasError ? null : "yes" })}>has error</FilterChip>
              <span className="mono ml-auto text-[11px] text-muted-foreground max-[900px]:ml-0 max-[900px]:mt-1 max-[900px]:w-full"><b className="text-foreground">{rows.length}</b> runs{capNote} · filters live in the URL</span>
            </div>
            <RunTable rows={rows} params={params} />
          </section>
          {detail && selectedSummary && <Evidence detail={detail} summary={selectedSummary} />}
        </main>
      )}
    </div>
  );
}
