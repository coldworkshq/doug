import { withAuth } from "@workos-inc/authkit-nextjs";
import Link from "next/link";
import { redirect } from "next/navigation";

import { signOutAction } from "@/app/auth/actions";
import { DougLogo } from "@/components/doug-logo";
import { dashboardFilters } from "@/lib/dashboard-model";
import {
  governingLine,
  mergeCaption,
  mergedHeadLine,
  windowOutcome,
  windowPreregLine,
} from "@/lib/receipt-merge-view";
import type {
  ReceiptMerge,
  ReceiptPreregistration,
  ReceiptResponse,
  ReceiptVerdict,
  ReceiptWindow,
} from "@/lib/receipt-shape";
import {
  type VerdictGap,
  latestVerdictCaption,
  promptHashLine,
  readLine,
  verdictGap,
} from "@/lib/receipt-verdict-view";
import { outcomeToneClass, utcTimestamp } from "@/lib/runs-time";
import { SessionApiError, getReceipt } from "@/lib/session-api";

/** THIS PAGE DECIDES NOTHING.
 *
 *  Nothing in this suite RENDERS. `lib/design-system.test.mjs` and
 *  `lib/dashboard-contract.test.mjs` do read `.tsx` files, but they read them
 *  as text: a source pin can assert that a string is present and cannot
 *  exercise a branch. So a judgment made here — a `?:` picking a word, a `??`
 *  filling an absent value — is a judgment no test can execute. Every
 *  sentence this screen makes about the evidence therefore comes back from a
 *  tested function in `lib/receipt-verdict-view.ts` or
 *  `lib/receipt-merge-view.ts`; what is left here is layout, plus the
 *  presence gates named in their own comments below.
 *
 *  The design grammar is the dashboard's, copied rather than imported: the
 *  constants below live in `app/dashboard/page.tsx`, which is a route module
 *  and not a place to import values from. They are duplicated deliberately
 *  and stay in lockstep by being identical strings. */
const CANVAS = "mx-auto w-full max-w-[1440px]";

const BLOCK_HEADING =
  "mono mb-3 flex items-center gap-2.5 text-[11px] font-medium uppercase tracking-[.16em] " +
  "text-muted-foreground [&_span]:text-[9.5px] [&_span]:normal-case [&_span]:tracking-[.04em] " +
  "[&_span]:text-[var(--dim)]";

const BLOCK = "border-b border-border py-[22px]";

const ROUTE = "rounded-[3px] bg-accent px-[7px] py-0.5 text-[var(--iridescent)] tracking-[.06em]";

const EMPTY_PAGE = "mx-auto max-w-[760px] px-6 py-[110px]";
const EMPTY_HEADING =
  "font-heading mt-[18px] text-[clamp(36px,7vw,64px)] font-semibold tracking-[-.05em]";
const EMPTY_BODY = "mt-4 max-w-[620px] text-base text-muted-foreground";

const EMPTY_NOTE = "text-xs text-muted-foreground";

/** The label/value grammar of the dashboard's evidence pane, verbatim. */
const DL = "mono grid grid-cols-[130px_1fr] gap-x-[18px] gap-y-2 text-[12px]";

type Failure = "missing" | "expired" | "unavailable" | "unreachable";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="uppercase text-muted-foreground">{label}</dt>
      {/* break-words, not break-all: a 40-character sha has to be able to
          wrap, and the publication note in the same column is prose that must
          not break mid-word to make room for it. */}
      <dd className="m-0 break-words whitespace-pre-wrap">{children}</dd>
    </>
  );
}

/** The dashboard's header, minus the two controls that need the connection
 *  list. Scope is not chosen here — it arrives in the query string with the
 *  PR number, from the row that linked to this page. */
function Frame({ email, children }: { email: string; children: React.ReactNode }) {
  return (
    <div className="dashboard-surface">
      <header
        className={`${CANVAS} sticky top-0 z-20 flex min-h-[52px] items-center gap-[18px] border-b border-border bg-background/[.88] px-5 py-2 backdrop-blur-[10px] max-[900px]:static max-[900px]:flex-wrap max-[900px]:items-start`}
      >
        <Link
          href="/"
          className="font-heading flex items-center gap-2 text-base font-bold text-inherit no-underline"
        >
          <DougLogo size={20} /> doug{" "}
          <span className="mono ml-0.5 rounded-[3px] bg-accent px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-[.12em] text-[var(--iridescent)]">
            receipt
          </span>
        </Link>
        <Link
          href="/dashboard"
          className="mono text-[11.5px] text-muted-foreground no-underline hover:text-foreground"
        >
          ← runs
        </Link>
        <div className="mono ml-auto flex items-center gap-2.5 text-[11.5px] text-muted-foreground max-[900px]:ml-0 max-[900px]:w-full max-[900px]:justify-end">
          <span>{email}</span>
          <form action={signOutAction}>
            <button type="submit" className="cursor-pointer border-0 bg-transparent text-inherit underline">
              sign out
            </button>
          </form>
        </div>
      </header>
      {children}
    </div>
  );
}

/** Four states, four sentences, no shared "something went wrong".
 *
 *  A table rather than a branch: the arm is chosen once, at the fetch, by the
 *  API's own status contract, and this only prints what that choice already
 *  decided. `expired` reuses the words #99/#100 shipped for
 *  `reauthorize_required` rather than inventing a second expiry story, and
 *  the control it asks for — sign out — is the one already in the header
 *  above.
 *
 *  `unreachable` is the fourth arm, and it exists because the other three are
 *  each a claim. It is the only one reached without a status the API chose,
 *  so it is the only one that names no cause and asks for nothing: telling a
 *  reader to sign back in over a dropped connection would be exactly the
 *  confident false claim this document is built to make impossible. */
const UNLOADABLE: Record<Failure, { route: string; heading: string; body: string }> = {
  missing: {
    route: "/prs",
    heading: "No receipt for this pull request.",
    body:
      "Doug has no verdict and no merge recorded for it. A pull request that does not " +
      "exist and one in a repository outside this space read identically here, on " +
      "purpose: the API answers both with the same code and the same body, so this " +
      "page cannot be used to find out whether someone else's repository exists.",
  },
  unavailable: {
    route: "/prs",
    heading: "The ledger is not answering.",
    body:
      "This is a deployment fault — no ledger, or no operator secret — and not a " +
      "problem with your session. Nothing is rendered below because nothing is known.",
  },
  expired: {
    route: "/spaces",
    heading: "Sign back in to refresh this.",
    body:
      "Doug still has your connection. What expired is the repository scope GitHub " +
      "granted when you signed in — it lasts eight hours, and only a new sign-in can " +
      "renew it. Sign out from the header above, then sign back in.",
  },
  unreachable: {
    route: "/prs",
    heading: "Doug could not load this receipt.",
    body:
      "The request came back with nothing this page can read. Which link in the chain " +
      "gave way is not something Doug can tell from here, so it is not named — and " +
      "nothing about your session or the pull request is claimed either way. Nothing " +
      "is rendered below because nothing is known.",
  },
};

function Unloadable({ failure }: { failure: Failure }) {
  const copy = UNLOADABLE[failure];
  return (
    <main className={EMPTY_PAGE}>
      <p className={`mono inline-block text-[10px] uppercase ${ROUTE}`}>{copy.route}</p>
      <h1 className={EMPTY_HEADING}>{copy.heading}</h1>
      <p className={EMPTY_BODY}>{copy.body}</p>
      <Link
        href="/dashboard"
        className="mono mt-[26px] inline-block rounded-[4px] border border-border px-3.5 py-2.5 text-[11px] no-underline"
      >
        Back to the run ledger
      </Link>
    </main>
  );
}

/** The score carries NO data colour, and that is not an oversight.
 *
 *  `ReceiptVerdict.band` is typed `string` on the wire (receipt-shape.ts —
 *  the validator deliberately does not narrow it), while `BandChip` and
 *  `.data-flag`/`.data-clear` take the closed `"cleared" | "flagged"` union.
 *  Bridging the two needs either a cast — which would paint an unrecognised
 *  band in the CLEARED colour, exactly the class of error #93 was about — or
 *  a `band === "flagged"` ternary decided here, where no test can reach it.
 *  So the band renders as its own word, in ink, beside the number it
 *  belongs to. See the report for the missing narrowing function. */
function VerdictCard({ verdict }: { verdict: ReceiptVerdict }) {
  return (
    <div className="panel rounded-[6px] p-4">
      <div className="mono flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
        <strong className="text-[28px] font-medium">{verdict.score.toFixed(2)}</strong>
        <span className="text-[11px] uppercase tracking-[.1em] text-muted-foreground">
          {verdict.band} · threshold {verdict.threshold.toFixed(2)}
        </span>
      </div>
      <dl className={`${DL} mt-3.5`}>
        <Row label="verdict">{verdict.verdict_id}</Row>
        <Row label="scored at">{utcTimestamp(verdict.scored_at)}</Row>
        <Row label="tier">{verdict.tier}</Row>
        {/* Both lines are the tested functions' words, not this file's.
            `readLine` trusts the API's `recorded` AND of the two columns —
            half a pair describes no instrument — and `promptHashLine` says
            "not stamped" for a row that predates prompt-hash stamping,
            never a match against the frozen prompt. */}
        <Row label="read">{readLine(verdict.read)}</Row>
        <Row label="prompt hash">{promptHashLine(verdict)}</Row>
      </dl>
    </div>
  );
}

/** Chrome colours — `--iridescent` over `bg-accent` — never `--flag`.
 *  The gap between what Doug says now and what was standing at the merge is
 *  a fact about two verdicts, not a verdict about the PR, and painting it in
 *  the miss colour would read as an alarm about the code. */
function GapBanner({ gap }: { gap: VerdictGap }) {
  return (
    <div className="mono mt-4 flex flex-col gap-1 rounded-[5px] border border-[var(--iridescent)] bg-accent px-3 py-2.5 text-[11.5px]">
      <span className="font-medium text-[var(--iridescent)]">
        The latest verdict is not the one that governed publication.
      </span>
      <span className="break-words text-muted-foreground">
        Verdict {gap.latestId} is Doug&apos;s most recent score. Verdict {gap.governingId} was
        standing when {gap.mergeSha} merged, and is the one the published statistic uses. Both
        are on this page.
      </span>
    </div>
  );
}

function WindowTile({
  entry,
  prereg,
}: {
  entry: ReceiptWindow;
  prereg: ReceiptPreregistration;
}) {
  // Word and tone come from the same call, so this tile cannot show one
  // window's colour beside another window's word. `censored` returns the
  // NEUTRAL tone: it records an outcome nobody could observe, and a
  // non-observation is not a miss (#93).
  const outcome = windowOutcome(entry);
  return (
    <div className="flex flex-col border border-border bg-card p-3">
      <span className="mono text-[10.5px] text-muted-foreground">{entry.window_days}-day window</span>
      <strong className={`mono my-1 text-[16px] ${outcomeToneClass(outcome.tone)}`}>
        {outcome.text}
      </strong>
      <span className="mono text-[10.5px] text-muted-foreground">due {utcTimestamp(entry.due_at)}</span>
      {/* A stamped window prints its OWN hash forever; only a window with no
          stamp names what will govern it. Reprinting today's in-force hash
          over an adjudicated window is the one claim this document exists to
          prevent, and `windowPreregLine` is where that rule is tested. */}
      <span className="mono mt-2 break-words text-[10.5px] text-muted-foreground">
        {windowPreregLine(entry, prereg)}
      </span>
    </div>
  );
}

function MergeCard({
  merge,
  total,
  prereg,
}: {
  merge: ReceiptMerge;
  total: number;
  prereg: ReceiptPreregistration;
}) {
  return (
    <article className="panel rounded-[6px] p-4">
      {/* `mergeCaption` is silent on a single-merge PR — there is nothing to
          disambiguate — and the empty string renders as nothing in the
          heading's provenance slot, with no branch here to make it so. */}
      <h3 className={`${BLOCK_HEADING} flex-wrap`}>
        Merge <span>{mergeCaption(merge, total)}</span>
      </h3>
      <dl className={DL}>
        <Row label="merge commit">{merge.merge_commit_sha}</Row>
        <Row label="merged at">{utcTimestamp(merge.merged_at)}</Row>
        <Row label="base">{merge.base_ref}</Row>
        {/* Null on a pre-migration-008 merge and on a deleted fork branch —
            "not recorded", never a sha inferred from anywhere else. */}
        <Row label="merged head">{mergedHeadLine(merge)}</Row>
        {/* A merge with no governing verdict says so. This never falls back
            to `latest_verdict`: that would claim advice was standing at a
            merge it was not standing at. */}
        <Row label="governing">{governingLine(merge)}</Row>
      </dl>
      <div className="mt-3.5 grid grid-cols-[repeat(auto-fit,minmax(215px,1fr))] gap-2.5">
        {merge.adjudication.map((entry) => (
          <WindowTile key={entry.window_days} entry={entry} prereg={prereg} />
        ))}
      </div>
      {/* Presence gate, not a judgment: a merge whose windows are absent says
          so rather than ending in silence, the same way the dashboard's
          evidence pane states an empty findings list. */}
      {merge.adjudication.length === 0 && (
        <p className={`${EMPTY_NOTE} mt-3`}>No observation window is recorded for this merge.</p>
      )}
    </article>
  );
}

function ReceiptDocument({ receipt }: { receipt: ReceiptResponse }) {
  const gap = verdictGap(receipt);
  return (
    <main>
      <div
        className={`mono ${CANVAS} flex items-center gap-3 px-5 pt-[26px] pb-3 text-[11px] uppercase tracking-[.15em] text-muted-foreground`}
      >
        <span className={ROUTE}>/prs/{receipt.pr_number}</span> Receipt
        <span className="h-px flex-1 bg-border" />
      </div>
      <section className={`${CANVAS} px-5 pb-14`} aria-labelledby="receipt-title">
        <h1
          id="receipt-title"
          className="font-heading border-b border-border pb-[22px] text-[clamp(22px,2.2vw,30px)] font-semibold leading-[1.1] tracking-[-.035em]"
        >
          {receipt.repo} <span className="text-muted-foreground">#{receipt.pr_number}</span>
        </h1>

        <section className={BLOCK}>
          <h2 className={BLOCK_HEADING}>
            Pre-registration <span>in force now — not necessarily what governed a window below</span>
          </h2>
          {/* The literal `prereg_hash: null` is the question this block
              answers: "what governs a window that carries no stamp of its
              own". That is `windowPreregLine`'s null branch exactly, so the
              in-force hash and the unset case are both worded by the tested
              function rather than by a `??` here. A PR-level `preregLine` is
              the function this block would rather call; see the report. */}
          <p className="mono break-words text-[12px]">
            {windowPreregLine({ prereg_hash: null }, receipt.preregistration)}
          </p>
        </section>

        <section className={BLOCK}>
          <h2 className={BLOCK_HEADING}>
            Latest verdict <span>what Doug says now</span>
          </h2>
          {/* Presence gate. The caption below renders either way, because the
              reason this can be absent — external reviews are excluded from
              it — is exactly what the caption explains. */}
          {receipt.latest_verdict === null ? (
            <p className={EMPTY_NOTE}>No Doug verdict is recorded for this pull request.</p>
          ) : (
            <VerdictCard verdict={receipt.latest_verdict} />
          )}
          <p className={`${EMPTY_NOTE} mt-3`}>{latestVerdictCaption()}</p>
          {/* Presence gate on a tested decision: `verdictGap` returns null
              unless a publication-governing merge carries a governing verdict
              that is not the latest one. It names both ids and the merge. */}
          {gap && <GapBanner gap={gap} />}
        </section>

        <section className={BLOCK}>
          <h2 className={BLOCK_HEADING}>
            Merges <span>{receipt.merges.length}</span>
          </h2>
          {/* The ordinary open-PR case, not an error. */}
          {receipt.merges.length === 0 && (
            <p className={EMPTY_NOTE}>not merged — no window has started</p>
          )}
          <div className="flex flex-col gap-4">
            {/* EVERY merge, in order. A PR carries a list — revert-and-reland
                is ordinary — and exactly one of them governs publication. */}
            {receipt.merges.map((merge) => (
              <MergeCard
                key={merge.merge_commit_sha}
                merge={merge}
                total={receipt.merges.length}
                prereg={receipt.preregistration}
              />
            ))}
          </div>
        </section>
      </section>
    </main>
  );
}

export default async function ReceiptPage({
  params,
  searchParams,
}: {
  params: Promise<{ number: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { number } = await params;
  const query = await searchParams;
  const auth = await withAuth();
  const { user, accessToken } = auth;
  if (!user || !accessToken) redirect("/sign-in");
  const email = user.email;
  // The same reader the dashboard's run list uses, so the two surfaces cannot
  // disagree about which repository `?repo=` names. A PR number alone is
  // ambiguous across repositories, which is why the API requires it.
  const repo = dashboardFilters(query).repo;
  const prNumber = Number(number);

  // A path segment that is not a positive integer names no pull request — the
  // same fact the API's 404 states, so it renders the same state. Sending it
  // on would fail the endpoint's `pr_number: int` path type with a 422, which
  // the arm below would tell as an expiry story about a session that is fine.
  // Precedent: console/app/runs/[verdictId]/page.tsx guards its id likewise.
  if (!Number.isInteger(prNumber) || prNumber < 1) {
    return (
      <Frame email={email}>
        <Unloadable failure="missing" />
      </Frame>
    );
  }

  // ONE variable, not two, and no JSX inside the try — `react-hooks/
  // error-boundaries` rejects constructing an element there, because React
  // renders it after the try has exited and the catch would never see its
  // error. Two independent `let`s would type as `receipt: … | null` beside
  // `failure: … | null`, whose fourth combination — nothing loaded and no
  // reason why — cannot happen (`getReceipt` resolves a validated body or
  // throws) but would still demand copy. Inventing a sentence for an
  // unreachable state is how a page learns to say something it cannot know,
  // so the union removes the state instead.
  let loaded: { receipt: ReceiptResponse; failure: null } | { receipt: null; failure: Failure };
  try {
    loaded = { receipt: await getReceipt(accessToken, repo, prNumber), failure: null };
  } catch (error) {
    const status = error instanceof SessionApiError ? error.status : null;
    // 404 covers BOTH "no such PR" and "not your repo", deliberately: the API
    // gives them one code AND one body so a caller cannot use this endpoint to
    // probe another tenant's repository names. Rendering them differently here
    // would rebuild the leak the API refused to open.
    let failure: Failure;
    if (status === 404) failure = "missing";
    // 503 is a deployment fault — no ledger, or no operator secret. The API
    // checks it BEFORE the token precisely so a misconfiguration is not
    // reported as a bad credential, and this must not undo that.
    else if (status === 503) failure = "unavailable";
    // 401 ONLY. `sessionJson` throws status:null on a transport failure AND on
    // a body the validator rejects; a 500 or 502 is neither. Routing any of
    // those to the expiry copy tells a reader to sign out and back in over a
    // network blip — a confident false claim on the one surface built to make
    // those impossible.
    else if (status === 401) failure = "expired";
    else failure = "unreachable";
    loaded = { receipt: null, failure };
  }

  return (
    <Frame email={email}>
      {loaded.receipt === null ? (
        <Unloadable failure={loaded.failure} />
      ) : (
        <ReceiptDocument receipt={loaded.receipt} />
      )}
    </Frame>
  );
}
