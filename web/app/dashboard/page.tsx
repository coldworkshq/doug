import { withAuth } from "@workos-inc/authkit-nextjs";
import Link from "next/link";
import { redirect } from "next/navigation";

import { signOutAction } from "@/app/auth/actions";
import { DougLogo } from "@/components/doug-logo";
import {
  capSuffix,
  coverageView,
  dashboardFilters,
  filterRuns,
  outcomeTone,
  repositoryOptions,
} from "@/lib/dashboard-model";
import {
  getConnections,
  getSessionRun,
  getSessionRuns,
  type RepositoryConnection,
  type RunDetail,
  type RunSummary,
} from "@/lib/session-api";

import { finishSetupAction, switchConnectionAction } from "./actions";
import styles from "./dashboard.module.css";

const LEMA_LABEL = "Lema — separate product";

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

function displayAge(timestamp: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(timestamp).getTime()) / 1000);
  if (seconds < 3600) return `${Math.max(1, Math.floor(seconds / 60))}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86400)}d`;
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
    <form action={switchConnectionAction} className={styles.scopeForm}>
      <label className={styles.switchControl}>
        <span>space</span>
        <select
          name="organization_id"
          defaultValue={current?.organization_id ?? ""}
          aria-label="Connected space"
        >
          {!current && <option value="" disabled>choose</option>}
          {ready.map((connection) => (
            <option key={connection.installation_id} value={connection.organization_id ?? ""}>
              {connectionLabel(connection)}
            </option>
          ))}
        </select>
      </label>
      <button type="submit" className={styles.scopeSubmit}>open</button>
    </form>
  );
}

function PendingConnections({ connections }: { connections: RepositoryConnection[] }) {
  const pending = connections.filter(
    (connection) => connection.status === "setup_required",
  );
  if (pending.length === 0) return null;
  return (
    <section className={styles.setupStrip} aria-labelledby="pending-connections-title">
      <div className={styles.setupHeading}>
        <span id="pending-connections-title">setup required</span>
        <small>Finish binding these installations before opening their run ledger.</small>
      </div>
      <div className={styles.setupRows}>
        {pending.map((connection) => (
          <div className={styles.setupRow} key={connection.installation_id}>
            <span>
              <strong>{connectionLabel(connection)}</strong>
              <small>{connection.account_type.toLowerCase()} · {connection.repositories.length} repositories</small>
            </span>
            <form action={finishSetupAction}>
              <input type="hidden" name="installation_id" value={connection.installation_id} />
              <button type="submit">finish setup</button>
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
  return <Link className={styles.chip} data-active={active || undefined} href={target}>{children}</Link>;
}

function CoverageCell({ run }: { run: RunSummary }) {
  const view = coverageView(run);
  if (view.percent === null) return <span className={styles.muted}>no read</span>;
  return (
    <div className={styles.coverageCell} title={view.chars ?? undefined}>
      <span className={styles.miniRuler}>
        <span style={{ width: `${view.percent}%` }} />
      </span>
      <span>{view.percent}%</span>
    </div>
  );
}

function RunTable({ rows, params }: { rows: RunSummary[]; params: DashboardParams }) {
  return (
    <div className={styles.tableScroll}>
      <table className={styles.runs}>
        <thead>
          <tr>
            <th>score</th><th>pull request</th><th>band</th><th>tier</th>
            <th>read</th><th>outcome</th><th>job</th><th>age</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((run, index) => (
            <tr key={run.verdict_id} style={{ animationDelay: `${index * 18}ms` }}>
              <td className={styles.numeric}>
                <span className={run.band === "flagged" ? styles.flag : styles.clear}>
                  {run.score.toFixed(2)}
                </span>
              </td>
              <td>
                <Link className={styles.subject} href={href(params, { run: String(run.verdict_id) })}>
                  <span><b>{run.repo}</b> #{run.pr_number}</span>
                  <strong>{run.title}</strong>
                </Link>
              </td>
              <td><span className={run.band === "flagged" ? styles.bandFlag : styles.bandClear}>
                {run.band === "flagged" ? "needs you" : "cleared"}
              </span></td>
              <td><span className={styles.monoValue}>{run.tier}</span></td>
              <td><CoverageCell run={run} /></td>
              <td><span className={styles.monoValue}>{run.outcome_14 ?? "—"}</span></td>
              <td><span className={run.job?.error ? styles.jobError : styles.monoValue}>
                {run.job?.error ? `${run.job.attempts}× · ${run.job.error}` : (run.job?.status ?? "—")}
              </span></td>
              <td className={styles.numeric}><span className={styles.monoValue}>{displayAge(run.scored_at)}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && <p className={styles.tableEmpty}>No runs match these filters.</p>}
    </div>
  );
}

function Evidence({ detail, summary }: { detail: RunDetail; summary: RunSummary }) {
  const view = coverageView({ coverage: detail.coverage, changed_files: summary.changed_files });
  return (
    <section className={styles.forensics} aria-labelledby="run-evidence-title">
      <header className={styles.evidenceHead}>
        <div>
          <p className={styles.crumb}>/runs/{detail.verdict_id} · {detail.repo} · #{detail.pr_number}</p>
          <h2 id="run-evidence-title">{summary.title}</h2>
        </div>
        <div className={styles.verdictBlock}>
          <strong className={detail.band === "flagged" ? styles.flag : styles.clear}>
            {detail.score.toFixed(2)}
          </strong>
          <span>{detail.band === "flagged" ? "needs you" : "cleared"} · threshold {detail.threshold.toFixed(2)}</span>
        </div>
      </header>

      <div className={styles.forensicGrid}>
        <aside className={styles.spine}>
          <h3>The run</h3>
          <div className={styles.event}><i /><b>scored</b><span>{new Date(detail.scored_at).toLocaleString()}</span></div>
          {detail.job && <div className={styles.event}><i /><b>job · {detail.job.status}</b><span>attempt {detail.job.attempts}</span></div>}
          {detail.coverage && <div className={styles.event}><i /><b>read</b><span>{detail.coverage.files_sent} files sent</span></div>}
          {detail.outcome_jobs.map((outcome) => (
            <div className={styles.event} key={`${outcome.window_days}-${outcome.due_at}`}>
              <i /><b>{outcome.window_days}d outcome · {outcome.status}</b>
              <span>due {new Date(outcome.due_at).toLocaleDateString()}</span>
            </div>
          ))}
        </aside>

        <div className={styles.evidence}>
          <section className={styles.block}>
            <h3>What the reader was given <span>reader evidence</span></h3>
            {detail.coverage ? (
              <div className={styles.rulerPanel}>
                <div className={styles.rulerTop}>
                  <strong>{view.percent === null ? "—" : `${view.percent}%`}</strong>
                  <span>{[view.files, view.chars].filter(Boolean).join(" · ")}</span>
                  {view.fileCut && <span>cut at <code>{view.fileCut}</code></span>}
                </div>
                <div className={styles.coverageRuler} aria-label={view.percent === null ? "coverage unknown" : `${view.percent}% of diff sent`}>
                  {view.percent !== null && <span style={{ width: `${view.percent}%` }} />}
                  {view.percent !== null && <i style={{ left: `${view.percent}%` }} />}
                </div>
                <div className={styles.rulerLegend}><span><i />sent to the reader</span><span><i />never read</span></div>
                {view.unseen.length > 0 && <div className={styles.unseen}>
                  <p>Unseen — {view.unseen.length} files</p>
                  {view.unseen.map((file) => <div key={file}><code>{file}</code><span>not read</span></div>)}
                </div>}
              </div>
            ) : <p className={styles.emptyNote}>No reader coverage was recorded for this run.</p>}
          </section>

          <section className={styles.block}>
            <h3>The read</h3>
            <dl className={styles.facts}>
              <dt>tier</dt><dd>{detail.tier}</dd>
              <dt>model</dt><dd>{detail.model ?? "not recorded"}</dd>
              <dt>prompt hash</dt><dd>{detail.prompt_hash ?? "not stamped"}</dd>
              <dt>risk score</dt><dd>{detail.risk_score ?? "not recorded"}</dd>
              <dt>head sha</dt><dd>{detail.head_sha ?? "not recorded"}</dd>
              <dt>rationale</dt><dd>{detail.rationale ?? "No rationale was recorded."}</dd>
            </dl>
          </section>

          <section className={styles.block}>
            <h3>Findings <span>{detail.reasons.length}</span></h3>
            {detail.reasons.map((reason) => (
              <div className={styles.finding} key={`${reason.rule}-${reason.label}`}>
                <span>{reason.severity ?? "rule"}</span>
                <div><code>{reason.rule}</code><p>{reason.label}</p></div>
              </div>
            ))}
            {detail.reasons.length === 0 && <p className={styles.emptyNote}>No findings recorded.</p>}
          </section>

          <section className={styles.block}>
            <h3>Deviations <span>separate stream</span></h3>
            {detail.deviations.map((deviation) => (
              <div className={styles.finding} key={`${deviation.type}-${deviation.description}`}>
                <span>{deviation.severity}</span><div><code>{deviation.type}</code><p>{deviation.description}</p></div>
              </div>
            ))}
            {detail.deviations.length === 0 && <p className={styles.emptyNote}>No deviations recorded.</p>}
          </section>

          <section className={styles.block}>
            <h3>Outcome</h3>
            <div className={styles.outcomes}>
              {detail.outcomes.map((outcome) => {
                const tone = outcomeTone(outcome.kind);
                const toneClass = tone === "clear"
                  ? styles.outcomeClear
                  : tone === "flag"
                    ? styles.outcomeFlag
                    : styles.outcomeNeutral;
                return <div key={`${outcome.window_days}-${outcome.observed_at}`}>
                  <span>{outcome.window_days ?? "?"}-day window</span>
                  <strong className={toneClass}>{outcome.kind}</strong>
                  <small>observed {new Date(outcome.observed_at).toLocaleDateString()}</small>
                </div>;
              })}
              {detail.outcomes.length === 0 && <p className={styles.emptyNote}>No outcome recorded yet.</p>}
            </div>
          </section>
        </div>
      </div>
    </section>
  );
}

function NoConnection({ userLabel }: { userLabel: string }) {
  return (
    <main className={styles.emptyState}>
      <p className={styles.route}>/account</p>
      <h1>{userLabel}, you&apos;re in.</h1>
      <p>{"You're in. Connect GitHub only when you want Doug to review repositories."}</p>
      <Link href="/install/start" prefetch={false} className={styles.primaryAction}>Connect GitHub</Link>
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
    <div className={styles.console}>
      <header className={styles.bar}>
        <Link href="/" className={styles.brand}><DougLogo size={20} /> doug <span>dashboard</span></Link>
        <ScopePicker connections={connections} current={current} />
        {current && <form method="GET" className={styles.repoForm}>
          <label className={styles.switchControl}>
            <span>repo</span>
            <select name="repo" defaultValue={filters.repo} aria-label="Repository">
              {repositoryOptions(current).map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>
          <button type="submit" className={styles.scopeSubmit}>filter</button>
        </form>}
        <Link href="/install/start" prefetch={false} className={styles.connectRepositories}>Connect repositories</Link>
        <div className={styles.account}>
          <span>{user.email}</span>
          <form action={signOutAction}><button type="submit">sign out</button></form>
        </div>
      </header>
      <nav className={styles.tabs} aria-label="Dashboard sections">
        <Link href="/dashboard" aria-current="page">Runs</Link>
        <span>Repositories <small>later</small></span>
        <span>Evidence <small>later</small></span>
      </nav>
      <PendingConnections connections={connections} />

      {connections.length === 0 ? <NoConnection userLabel={userLabel} /> : !current ? (
        <main className={styles.chooseState}>
          <p className={styles.route}>/spaces</p>
          <h1>Choose a connected space.</h1>
          <p>Each space stays separate. Runs from one installation never join another.</p>
          <ScopePicker connections={connections} current={null} />
        </main>
      ) : (
        <main>
          <div className={styles.screenLabel}><span>/runs</span> Verdict history for {connectionLabel(current)}</div>
          <section className={styles.frame}>
            <div className={styles.filters}>
              <FilterChip active={filters.band === "all" && filters.tier === "all" && !filters.lowCoverage && !filters.hasError} target={href(params, { band: null, tier: null, coverage: null, error: null })}>all</FilterChip>
              <FilterChip active={filters.band === "flagged"} target={href(params, { band: filters.band === "flagged" ? null : "flagged" })}>needs you</FilterChip>
              <FilterChip active={filters.band === "cleared"} target={href(params, { band: filters.band === "cleared" ? null : "cleared" })}>cleared</FilterChip>
              <FilterChip active={filters.tier === "reader"} target={href(params, { tier: filters.tier === "reader" ? null : "reader" })}>reader</FilterChip>
              <FilterChip active={filters.tier === "deterministic"} target={href(params, { tier: filters.tier === "deterministic" ? null : "deterministic" })}>deterministic</FilterChip>
              <FilterChip active={filters.lowCoverage} target={href(params, { coverage: filters.lowCoverage ? null : "low" })}>coverage &lt; 50%</FilterChip>
              <FilterChip active={filters.hasError} target={href(params, { error: filters.hasError ? null : "yes" })}>has error</FilterChip>
              <span className={styles.count}><b>{rows.length}</b> runs{capNote} · filters live in the URL</span>
            </div>
            <RunTable rows={rows} params={params} />
          </section>
          {detail && selectedSummary && <Evidence detail={detail} summary={selectedSummary} />}
        </main>
      )}
    </div>
  );
}
