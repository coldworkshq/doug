# doug-console Phase 2a — health strip and failure surface

Status: design, approved 2026-08-07
Supersedes: nothing. Corrects two lines of
`2026-08-06-doug-console-design.md` (see "Corrections to the Phase 1 design").

## Problem

The console cannot show a failing job, and the gap is structural rather than
an omission. `review_jobs.verdict_id` is set only by `ingest.complete()`,
which writes `status="done"` and `error=None` in the same UPDATE. Every
console surface is keyed on a verdict, so a verdict-keyed surface can never
carry a failure. Andrew ruled ship on this at Phase 1 with it recorded as
the first Phase 2 item.

The consequence in daily use is that silence and success are
indistinguishable. "Did Doug review that PR?" has no answer in the console
when the answer is no, and answering it means `psql`.

M3 makes this worse rather than better. The `doug-adjudicator` Cloud Run Job
and its 03:00 UTC Scheduler are live, and the first execution against a real
due clock lands around 2026-08-16. That is an entirely new failure lane, and
nothing in the console can show it failing either.

## Non-goals

- **No mutation.** No requeue, no retry, no clearing a failure. The
  complaint is "I cannot see the failure", not "I cannot click retry". A
  write path means a fencing contract against live claims, an idempotency
  story, and the console's first mutation review surface — roughly double
  the build, for an ergonomic gain we can add later once we know which
  failures actually recur.
- **No `installations.reconciled_at`.** The Phase 1 design lists it under
  `/v1/health`. The column does not exist; it is MT3 / migration 8 and
  unstarted. The design gets corrected rather than the endpoint faked.
- **No Cloud Run Job execution status.** Whether the 03:00 UTC execution
  fired lives in the Cloud Run API, not the ledger. The console must not
  claim to know it. `outcome_jobs.status='pending' AND due_at < now()` is
  the honest ledger-only proxy for "the adjudicator should have run and did
  not".
- **No render-test infrastructure.** Still its own Phase 2 item. This design
  routes around the gap rather than closing it, by keeping the classification
  logic in a pure module the existing `node --test` tooling can pin.
- `/v1/repos`, the Repos page and the Evidence page stay untouched.

## Decision 1 — two endpoints, split by claim

`GET /v1/health` returns aggregates and no rows. `GET /v1/jobs` returns rows
and no aggregates. Both are operator-only behind the existing
`_operator_only` gate, and both take the same `repo` / `installation_id`
scope parameters as `/v1/runs`.

The split follows from what each surface claims. The strip renders on every
page and claims "nothing is wrong right now", so it must be cheap enough for
that claim to stay true — a fixed set of aggregates over indexed columns and
no row data at all, whatever the size of the queue. The list claims "these
are the unhealthy jobs" and must carry its own
cap and denominator, because a page-cap printed as a total is the defect
Phase 1 already paid for once.

Rejected: one endpoint carrying counts and rows together. It makes the strip
pay row cost on every page load, gives the rows no independent pagination,
and fuses two failure modes — a slow row query would blank the very strip
that exists to say something is wrong.

Rejected: a job-keyed view mode on `/v1/runs`. That is the merged-table
option in API costume: `score`, `band`, `coverage` and `finding_counts` are
absent on every non-`done` row, so one endpoint would return two
incompatible row shapes behind a query parameter.

## Decision 2 — `GET /v1/health`

```
review:  pending, oldest_pending_at, retrying, oldest_retry_at,
         running, stalled, failed, failed_24h,
         stall_lease_seconds, max_attempts
outcome: pending, overdue, next_due_at, oldest_overdue_due_at,
         running, stalled, failed,
         stall_lease_seconds, max_attempts
as_of:   the server's now()
```

`pending` counts every pending row; `retrying` counts the subset with
`attempts > 0`, so fresh-pending is `pending - retrying`. `overdue` counts
pending outcome rows with `due_at < as_of`. `next_due_at` is the earliest
`due_at` still in the future — "when the next clock comes due" — and is
`null` when none is; `oldest_overdue_due_at` is the earliest already past,
and is what the grace in Decision 4 is measured against. The two never
overlap. The outcome lane has no `failed_24h`: its cap is ten attempts
against a daily cycle, so a terminal outcome failure is already days old by
construction and a 24-hour window would almost always read zero.

Seven properties of that shape are load-bearing.

**`oldest_pending_at` counts only rows with `attempts = 0`.** `ingest.fail()`
below the cap sets `enqueued_at = now`, deliberately, so a retry goes to the
back of the queue instead of burning all three attempts in one pass. A naive
`MIN(enqueued_at) WHERE status='pending'` therefore reports a twice-failed
job as freshly enqueued, and the metric goes blind to exactly the jobs most
likely to be in trouble. Splitting it keeps two different quantities apart:
`oldest_pending_at` means "the drain is not draining", `oldest_retry_at`
means "when the last attempt gave up". They must never be blended back into
one `MIN`.

**The constants are per lane, and a single pair would make the console lie.**
`ingest.STALL_LEASE_SECONDS` is 900 with `max_attempts=3`;
`outcome_queue.STALL_LEASE_SECONDS` is 7200 with `MAX_ATTEMPTS=10`. One
top-level `stall_lease_seconds: 900` would flag a healthy twenty-minute-old
outcome claim as stalled against a lease that is actually two hours, and
would render attempts as `4/3` on a lane whose cap is ten.

**The constants travel in the payload at all.** The console never hardcodes
900, 7200, 3 or 10. If a constant moves, the UI follows instead of silently
disagreeing with the sweep that enforces it.

**`as_of` is the server's clock.** Every age the UI displays is `as_of`
minus a timestamp, never the browser's. Phase 1 already paid for a timestamp
defect — values relabelled UTC after being parsed as local — and this is the
same defect with an alarm bolted on.

**`superseded` is counted nowhere.** `ingest.supersede()` is neither `done`
(no verdict) nor `failed` (nothing went wrong), and it lands revivable on
purpose. Counting it is the single easiest way to make this surface cry
wolf.

**The outcome lane needs no `attempts = 0` split.**
`outcome_queue._fail_job()` leaves `due_at` untouched on retry, so a
retrying outcome job stays correctly overdue and stays visible. The
asymmetry between the lanes is real and grounded in the two functions; it is
not an inconsistency to smooth over.

**No `healthy: true|false` from the server.** It returns counts. One pure
console function decides the presentation. A server-side boolean would put
the definition of "unhealthy" in two places that will drift.

### Index coverage, stated honestly

Three partial indexes from migration 3 already serve most of this:

| Index | Serves |
|---|---|
| `review_jobs (enqueued_at, id) WHERE status='pending'` | pending count, oldest ages |
| `review_jobs (started_at) WHERE status='running'` | stalled — `started_at < as_of - lease` |
| `outcome_jobs (due_at) WHERE status='pending'` | overdue, `next_due_at` |

Two caveats rather than a claim of free reads. Adding `attempts = 0` to the
pending predicate makes that scan no longer index-only; it stays a cheap
ordered scan of the pending set, which is small by construction. And
`outcome_jobs.status` carries no index at all — `review_jobs.status` has a
plain btree via `index=True`, `outcome_jobs.status` does not — so the
outcome failed-count is a sequential scan. The table is small enough today
that this is acceptable; it is recorded here so it is a known cost rather
than a future surprise.

## Decision 3 — `GET /v1/jobs`

Parameters: `lane` (`review` | `outcome`), `view` (`unhealthy` | `all`,
default `unhealthy`), `status`, `repo`, `installation_id`, `limit` (1–500,
default 100), `offset`. The response uses the same `{items, limit, offset}`
envelope as `/v1/runs`, so the existing `atCap` honesty machinery works
unchanged.

`status` accepts **stored** statuses only — the five in `review_jobs` and the
four in `outcome_jobs`. `stalled` and `retrying` are derived from
`started_at` and `attempts`, not stored, so they are not valid `status`
values and must not be smuggled in as if they were; that would put the
derivation in two places and let the list disagree with the strip. Derived
states are reachable through `view=unhealthy`, which is defined as exactly
the RED and AMBER rows of the Decision 4 table and nothing else. The
server owns that definition so the list and the strip cannot drift apart.

Each row carries the derived flags it was selected by (`stalled`,
`retrying`, and for the outcome lane `overdue`) alongside its stored status,
so the page renders the reason without recomputing it against a lease
constant it would have to hold locally.

**The outcome lane's repo name is genuinely nullable.** `review_jobs` carries
`repo_full_name` for display; `outcome_jobs` carries only `github_repo_id`.
The display name must come from `installation_repos.full_name`, which
`worker.py` already documents as able to go stale and which
`count_verdict_repos_missing_from_ledger()` proves can be absent entirely.
When the join misses, the row renders the bare `github_repo_id` — never a
guess, never a blank.

## Decision 4 — what "unhealthy" means

Every state is classified by whether it self-heals. `worker.drain()` calls
`ingest.reclaim_stalled()` once before its first claim, and the drain itself
is kicked by every webhook delivery and every container start, which is what
makes the self-healing column true rather than hopeful.

| State | Self-heals | Verdict |
|---|---|---|
| `review.failed` (attempts ≥ 3) | never | **RED** |
| `outcome.failed` (attempts ≥ 10) | never | **RED** |
| `outcome` pending past `due_at` + grace | only if the daily fire works, and it evidently did not | **RED** |
| `review.stalled` (running past 900s) | yes — `reclaim_stalled()` leads every drain | AMBER |
| `review.retrying` (pending, attempts > 0) | yes — a retry is armed | AMBER |
| `review.pending`, attempts 0, past threshold | yes — next webhook or cold start | AMBER |
| `outcome.stalled` (running past 7200s) | yes — same contract | AMBER |
| `done` with a verdict | — | green |
| `done` with no verdict (skipped) | — | green |
| `superseded` | — | counted nowhere |
| the health request itself failed | — | **UNKNOWN, never green** |

**`done` is two states, not one.** `ingest.complete()` takes
`verdict_id: int | None` — "a skipped PR is finished, not failed". A healthy
`done` job can carry a NULL verdict, so unlinkable does not mean unhealthy.
This is a third silent outcome today: Doug ran, declined to review, and left
no trace anywhere in the console. It renders as its own thing on `/jobs`,
never as a failure.

**The pending threshold is 15 minutes, and the console owns it too.** The
drain is kicked by every webhook delivery and every container start, and a
job's own delivery kicks a drain in the same request. So a fresh-pending job
that is still pending fifteen minutes later means the drain that should have
claimed it did not — several kick opportunities have passed. Like the
adjudicator grace, this number cannot come from the ledger: it is a
statement about how often drains are kicked, not about any stored value. It
lives beside the grace in `lib/health.ts` as a named, commented, tested
constant, and the strip states it in words — "oldest waiting 3h" — so the
reader sees the quantity rather than only the verdict.

**Overdue needs grace, and the console owns the number.** The adjudicator
fires daily at 03:00 UTC, so a job due at 00:00 is legitimately overdue for
three hours and any job can be legitimately overdue for most of a day.
Without grace this alarm is red every single day and is ignored inside a
week. The number cannot come from the API honestly — the schedule lives in
Cloud Scheduler, not in Python — so it lives in `lib/health.ts` as one
named, commented, tested constant of 26 hours (the 24-hour cycle plus
slack), and **the strip states the assumption in its own words**: "no
adjudicator pass in over 26h". When the schedule changes, the console says
something falsifiable rather than something quietly wrong. This is the one
number the console knows that the ledger does not, and it should be loud
about that rather than tidy.

**UNKNOWN is the load-bearing state.** A strip that renders green because
the health call timed out is strictly worse than no strip: it converts "I do
not know" into "everything is fine" on the one surface built to prevent
exactly that. It gets the treatment `lib/api.ts` already gives Runs —
explicit failure, no fixture, no fallback.

**Colour is never the only carrier.** Red already means "this PR needs a
human" in the band column; in the strip it would mean "Doug itself broke".
The Phase 1 palette rule stands: icon plus word plus count, so a greyscale
or colour-blind read loses nothing.

## Decision 5 — console surfaces

### The strip

It lives in `components/shell.tsx`, so it appears on `/`, `/runs/[id]` and
`/jobs` alike. It is server-rendered per page load. No polling: the pages
are already `force-dynamic`, so a refresh is a fresh read, and a polling
client component would need its own stale and error states — one more thing
that can render "clear" while being wrong.

**The strip is global, never scoped.** "Is Doug failing on anything" is a
global question, and a scope filter that can hide a fire in another tenant
is an anti-feature on this surface specifically. It says "across every
installation" in words, so it never appears to describe the filtered table
beneath it. A global strip reading "2 failed" above a repo-scoped table
showing none is correct, and the wording is what makes it read that way.

**It widens the Phase 1 placeholder.** `shell.tsx` already ships a ghosted
strip whose four cells are `running · pending · failed 24h · clocks due`,
every value an em dash and no hue, with a comment reserving that exact
layout for Phase 2. Four cells cannot carry the honest picture: they have
nowhere to put terminal-failed as distinct from failed-in-24h, retrying as
distinct from pending, stalled at all, or the UNKNOWN state. The visual
treatment is kept — one bordered strip of bordered cells, mono, tabular
figures. The cells become:

| Cell | Reads |
|---|---|
| verdict | the word `failing` / `degraded` / `clear` / `unknown`, with its icon |
| failed | terminal failures, both lanes, with `24h` alongside for the review lane |
| stalled | claims past their own lane's lease |
| waiting | fresh-pending count and the oldest age |
| retrying | pending with attempts, and the oldest age |
| clocks | outcome pending, `next_due_at`, and overdue-past-grace when non-zero |

Every cell renders its count and its word. A cell with nothing to report
renders `0` and stays legible; a cell in the UNKNOWN state renders neither a
count nor a zero.

### `/jobs`

Scoped like Runs — same `ScopeSwitch`, same `atCap`, same envelope. Two
labelled lane sections rather than one blended table, because the lanes
genuinely differ: the review lane is keyed on head SHA with a 900-second
lease and a cap of 3, the outcome lane on merge SHA with a due date, a
7200-second lease and a cap of 10. Blending them produces columns that are
empty for half the rows — the same objection that kept the spine
verdict-keyed, one level down.

The default filter is **unhealthy only**, with an explicit toggle to show
all. The page exists to answer "what is wrong", and a raw job list is
overwhelmingly `done` and `superseded`. The toggle must exist, because "the
job I expected does not exist at all" is a real diagnosis and only a
complete list reaches it.

Rows link to `/runs/[verdict_id]` when a verdict is present, and to nothing
when it is not.

`Shell`'s `active` prop is a single-member union (`"runs"`) and widens to
`"runs" | "jobs"`. The nav gains a Jobs tab; Repos and Evidence stay ghosted.

**Error text renders in full**, in a mono block, untruncated — operators need
the whole exception string. `review_jobs.error` is written from exception
text and could in principle contain a URL bearing a token. The console is
IAM-gated and read by someone who already holds the operator token, so this
is an accepted risk rather than an oversight. It is recorded here so that a
future public surface never inherits this field by copy-paste.

## Corrections to the Phase 1 design

`2026-08-06-doug-console-design.md` needs two amendments, both made by this
document:

1. Its `/v1/health` line lists "per-installation `reconciled_at`". That
   column does not exist and is not in this scope.
2. Its Phase 2 row reads "`/v1/repos`, Repos page, health strip". The health
   strip and the failure surface are split out as Phase 2a and ship first;
   `/v1/repos` and the Repos page become Phase 2b.

## Testing

`lib/health.ts` is a pure function over the `/v1/health` payload, tested with
the existing `node --test` pattern — no new infrastructure. Nearly all of the
lying-risk in this feature lives in that module by construction.

Tests encode why the behaviour matters:

- A `superseded` job counted as a failure **fails**. That is the cry-wolf
  path, and it is the most likely way this surface gets ignored.
- The strip rendering "clear" when the health request errored **fails**.
  Worst-case lie.
- An age computed from the client clock rather than `as_of` **fails**, with a
  fixture whose clocks are deliberately skewed.
- A pending age computed over rows with `attempts > 0` **fails**, with a
  fixture holding a twice-retried job whose `enqueued_at` was reset by
  `ingest.fail()` — the metric must not report it as fresh.
- `stalled` computed against a hardcoded lease rather than the lane's own
  `stall_lease_seconds` **fails**, with a fixture whose outcome-lane claim is
  older than 900s but younger than 7200s.
- Attempts rendered against the wrong lane's cap **fails**.
- An outcome job overdue by less than the 26-hour grace rendered red
  **fails**. That is the alarm-fatigue path.
- A `done` job with a NULL verdict rendered as a failure **fails**.
- A fresh-pending job younger than the 15-minute threshold rendered as
  degraded **fails**, and one older than it rendered as clear **fails** —
  the threshold has to bite in both directions or it is decoration.
- A `stalled` or `retrying` value accepted as a `status` query parameter
  **fails**, since that would put the derivation somewhere the strip cannot
  see.
- An outcome row whose `installation_repos` join missed, rendering a guessed
  repo name rather than the bare `github_repo_id`, **fails**.
- pytest: `/v1/health` or `/v1/jobs` answering without the operator token
  **fails** — the same fails-closed pin Phase 1 put on `/v1/runs`, and
  verified non-vacuous the same way.

## Open questions

None blocking implementation.
