# Reviewing changes to Doug

Doug reviews every PR here (ADR-0008), and agent reviewers review the work before it
becomes a PR. This file records what those two layers keep getting wrong, so the next
reviewer starts where the last one finished. Add to it when a review misses something —
a lesson that stays in one session's context is not a lesson.

## Verdicts on a fix must judge the replacement, not the removal

"ADDRESSED" means the defect no longer exists. It does not mean the line changed.

The case that produced this rule: a review found `ingest.claim()`'s docstring wrong about
why sqlite cannot double-claim a row. The fix round rewrote the sentence, the scoped
re-review verdicted it ADDRESSED — and the replacement was *also* wrong, in a subtler way
(it claimed a racing writer cannot read the row; sqlite's deferred transactions mean it
can, and the loser fails on its UPDATE with SQLITE_BUSY instead). Doug caught it on the PR,
one layer past both agent reviews.

When the fix is an explanation rather than a behavior change, the re-reviewer has to
evaluate the new explanation on its merits, against the mechanism it describes. A diff that
replaces a wrong claim with a different wrong claim reads exactly like a successful fix.

## A removed line is not current behavior

PR #56 removed a `try/finally` block that temporarily assigned the historical 30k
budget to `reader.DIFF_BUDGET`. The next Doug pass reported that deleted assignment as
a current global-mutation race even though `_probe_coverage` now passed
`budget=PROBE_DIFF_BUDGET` directly and the module contained no assignment to
`reader.DIFF_BUDGET` at all.

A patch shows both the old and new program. Before reporting behavior from a changed
hunk, check the line's polarity and then inspect the current file. A `-` line can explain
what the change fixes; it cannot prove what the resulting program still does. Settle a
claim about remaining behavior against the checked-out head, not by paraphrasing both
sides of the diff as if they coexist.

## A finding that depends on code outside the diff must say so

Doug reviews a diff, not a repository, and it reports two kinds of finding without
distinguishing them: things the diff proves, and things the diff merely permits. Two of its
five findings on PR #19 were the second kind — a datetime aware/naive concern that
`store.py` disproves (every column is `DateTime(timezone=True)`), and a duplicate-read
concern that `worker.py`'s head re-check answers.

Neither was a bad finding; both were unresolvable from what it was shown. Check the
surrounding code before fixing or dismissing, and record which one it was. The same rule
binds agent reviewers, who should mark these ⚠️ rather than assert them.

## Settle a resolution finding with the check that already ran

PR #28's `reader:missing-import` said `threading.Thread` was newly used with no
`import threading` in the diff. The import was already at `api/doug/api.py:7`, three tests
spawn that thread, and `ruff check` — which runs on every PR under
`select = ["E", "F", "I", "UP", "B"]` — was green before Doug emitted the finding. F821 is
undefined-name. **The falsifier had already run.**

Before disposing a finding about a name, an import, or a symbol, check whether CI already
answered it. Ruff's boundary, measured 2026-08-02 against a probe file with that exact
select list:

| ruff catches | ruff misses |
|---|---|
| `F821` undefined name, intra-file — including a function-scoped import referenced from another function | a `TYPE_CHECKING`-only import dereferenced at runtime (a live `NameError`) |
| `F403` / `F405` star imports | `from x import Y` where `Y` is absent from the target module |
| | an import of a module that does not exist at all |
| | `getattr(obj, "made_up_attribute", "")` |

Those four are the only places a resolution finding can still be real. Everything else in
the class is disproved by a command that ran green before the review started.

The general form is worth more than the table. **A claim about an absence cannot be settled
by looking at the same place the claim came from.** "No `import threading` was added" is a
fact about the diff; whether the import exists is a fact about the repo. Re-reading the diff
confirms the finding every time and proves nothing — the check and the error are the same
observation. Go to the file.

## Verify platform semantics before fixing a platform finding

PR #22 produced a plausible warning that a `neutral` check run might not satisfy a
required check in some GitHub configurations. That would undermine ADR-0010, but GitHub's
current documentation says the opposite: `success`, `skipped`, and `neutral` are
successful required-check states.

Claims about GitHub behavior need current primary-source evidence before they change code
or a decision record. If the documentation is clear, cite it in the disposition. If it is
not, reproduce the exact branch-protection or ruleset configuration. Do not turn “the
check is missing” or “the check came from the wrong expected App” into “`neutral`
blocks” — those are different failure modes. A required check can wait forever when no
result is posted; a posted `neutral` result satisfies the required status check.

Source checked 2026-08-01: [Troubleshooting required status
checks](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks#required-check-needs-to-succeed-against-the-latest-commit-sha).

## Read Doug's coverage line before trusting its verdict

Every verdict carries what was actually read: `Partial read: 83% of the diff (100,000 of
120,481 chars). Cut inside api/tests/test_ingest.py. Never sent: ROADMAP.md.` A clear on a
partial read is not evidence about the unread part, and Doug says so itself.

Since #308 the finding says it too. Every reader finding is tagged at emit
time with what the read held of the file it names (`reader.classify_by_coverage`,
from the same `Coverage` the verdict ships with): a file sent whole carries
nothing, the file the budget landed inside renders with _cites a file Doug
read only in part_, and a file never sent, never fetched, or never in the
diff at all renders with _cites code Doug did not read_ — the #175 shape,
`import sys` cited from a `worker.py` the PR never touched. The severity is
still the model's claim about consequence-if-true; the chip says how much of
the cited code that claim was made from. Such a finding sorts after its
in-read peers of the same severity and no lower, because a file the budget
dropped is also where a real defect can hide; the full discount by coverage
(#232, option 3) stays open until it is measured.

This is also a PR-size signal pointing the same way as one-PR-per-task: a diff small enough
to be read whole produces a verdict worth something. A 121k-char diff does not.

## The recurring defect class here is a comment that outlives its truth

Across these reviews the same shape keeps recurring: a docstring asserting a durability,
ordering, or concurrency property the code does not have. `ingest.py` claimed a dying
instance "loses a claim, not a review" while stranding it forever; `apply()` promised
"already done is satisfied, not failed" and then raised on a duplicate version row;
`claim()` explained a sqlite guarantee twice, wrongly both times.

These are not cosmetic. This product sells calibrated claims, and a comment is a claim with
no test behind it. When a docstring states a property, find the code that enforces it —
and if nothing does, the docstring is the bug.

## Mutation testing cannot see a property whose tests share an assumption with the code

A mutation battery answers "does any test notice this edit?" It cannot answer "does any test
supply an input that would make this edit matter?" So a property whose every test input is
drawn from the same assumption the code makes survives every mutant — and the survival reads
as coverage.

The case that produced this rule: `ingest._revive` picks the reconcile sweep's cooloff terms
with `trigger == "reconcile"`, and the comment above it states the fail-open direction as a
safety property — anything unrecognized takes the live branch, so a mistake costs spend rather
than a PR that 202s and is never reviewed. Rewritten as `trigger != "live"` it is identical
over the two values `Trigger` allows and inverted over every other one, which is the natural
edit the moment somebody adds a third trigger. The whole suite passed against that mutant,
through the implementer's battery, the controller's re-run of it, and every mutation either
ran, because all of them used valid triggers. `api.py`'s `REVIEW_BANDS` is the same shape with
the assumption in the fixtures: lowercase keys, lowercase states in every test payload, and a
GitHub REST API that spells those states uppercase.

The tell is a property that is load-bearing, stated in prose, and exercised only by inputs
drawn from the set the code already assumes — two enum values, one letter case, one SQL
dialect. The remedy is one input from outside that set, and the test is usually three lines,
which is why it is worth writing rather than arguing about.

Sweeping the rest of `ingest.py` for the shape found three more, left unfixed and recorded
here instead: `REVIVABLE` can be emptied to `()` with the suite green (nine comments across
four files cite it as what excludes `'running'` from revival; no code reads it — `_revive`
spells the statuses literally), `claim()`'s Postgres `SKIP LOCKED` branch can be disabled
outright because every test runs sqlite, which its own docstring says takes a different path,
and `reclaim_stalled`'s `max(0, rowcount)` clamp can be dropped. A green mutation run over
those is not evidence about them.

## Where the plan's own text is the defect

The step-2 plan carries literal code. Several times its sample violated a constraint the
same plan states in prose. The standing ruling is that plan **intent** governs over plan
**sample**, the fix goes in, and the ruling gets recorded in the PR body rather than
applied silently — the plan was reviewed by people who deserve to see where it was wrong.

## Doug's own findings: expect roughly half to be disproved by code it wasn't shown

Two rounds of Doug reviewing this branch produced nine findings. Four were real, two were
disproved by files outside the diff (`Coverage` declaring the field it was said to reject;
`save_deviations` always writing a row, so "no rows" means no read rather than a dropped
one), and three were "wrong as stated, right about something adjacent."

That last category is the valuable one and the easiest to throw away. Doug claimed the
replay path could reuse the wrong coverage for the intent read; it cannot, because
`coverage()` is a pure function of the diff. But the property was asserted in two docstrings
and enforced by nothing, and the replay path had just started depending on it — so the
finding was right that something was missing, and wrong about what. It bought a test.

The rule: before dismissing a finding, find the code that disproves it and say which file
that was. Before accepting one, check whether the fix it suggests is the fix the codebase
actually needs — Doug flagged the idempotency pre-read as advisory, and the useful response
was not to add a lock but to upgrade an already-planned index to a unique one.

## A pinned-SHA evidence script cannot run in a default CI checkout

`scripts/read_budget_gate.py` pins `END_SHA = "135c8e5"` and walks 30 first-parent
commits back from it. That pinning is right: the range is a fixed historical sample,
and `test_read_budget_scripts.py` asserts its exact result (24/30 at a 30k budget), so
a range that drifted with `HEAD` would assert nothing.

But `actions/checkout` defaults to `fetch-depth: 1`. The runner gets one commit, `git log
--first-parent -30 … 135c8e5` exits 128, and the test fails in CI while passing on every
developer clone — where the history is simply there. #56 merged with this failing, twice,
and the next branch to fork inherited a red suite it had not caused.

The general shape: **a test that reads git history has a dependency the test file never
names.** It is invisible in review, invisible locally, and only ever fails on the runner.
The same applies to anything reaching outside the working tree — tags, submodules,
`git describe`, blame.

When a test shells out to `git`, ask what the checkout must contain for it to pass, and
put that in the workflow next to the job rather than in the test. And when CI fails on a
branch, check whether the failing test even exists on that branch before debugging it:
here the suite went 691 → 703, which said immediately that the failure arrived with a
merge and not with the work.

## Log every finding, not only the ones that taught something

"Roughly half" above is an impression, not a measurement, and this file cannot make it one:
a finding that produced no lesson never got written down, so there is no denominator here
and never will be.

`docs/findings-log.jsonl` is the denominator. One line per finding, appended at disposition
time — when you already hold the answer, because the rule above already makes you name the
file that settled it before dismissing anything. It is transcription, not new work.

```json
{"date":"2026-08-02","pr":28,"layer":"doug","repo":"doug","rule":"reader:missing-import",
 "verdict":"disproved","changed":false,
 "settled_by":"api/doug/api.py:7 — already imported; ruff F821 green before the finding",
 "source":"prospective","note":"optional, one line"}
```

`repo` names the repository the PR belongs to, and it exists because `pr` does
not identify a review on its own — a PR number is only unique inside one
repository. Doug now reviews repositories it did not ship in (coldworks first),
and a rate computed across two of them describes neither. It is **optional in
the file and defaults to `doug`**, so the 135 rows written before that was true
stay valid without being rewritten; it is **required on the CLI**, so a new row
cannot land in doug's denominator by omission. `rate --repo <name>` is what any
published number should come from; an unscoped `rate` still prints `by_repo` so
a mixed figure cannot be quoted unaware. The value is a lowercase slug and the
schema refuses anything else, because a typo does not fail loudly — it silently
splits one repository's denominator in two.

`rule` is `<prefix>:<slug>`, **both halves kebab-case** (`[a-z0-9]+(-[a-z0-9]+)*`),
and the prefix names **the instrument that raised the finding** — `reader:` for the diff reader, `deviation:` / `beyond-ticket:` /
`missing-from-pr:` for the plan lane. More than one instrument writes to this
file and they do not speak the same vocabulary, so a share pooled across them is
a share of nothing: on 2026-08-27 the plan lane's 12 rows ran 75% real against
the reader's 48.3%, and pooling them published 50.0%. `patterns.from_rule`
already refuses to pool the two; `rate --rule-prefix reader:` is the equivalent
here, and an unscoped `rate` prints `by_rule_prefix` for the same reason it
prints `by_repo`. **The prefix is required** — the schema rejects an untagged
rule, because an untagged row does not fail loudly, it just lands in whichever
share is computed next. The slug is pinned too, because on the reader tier it is
`category_slug` — a free-form schema string with no enum and no pattern — so
`reader:Foo Bar` is reachable model output and would group as its own pattern
beside `reader:foo-bar`. Transcription is the last place that can refuse it: if
the reader emitted some other shape, kebab-case it here and put the original in
`note`. The 20 rows written before any of this was enforced were reader findings
recorded without the tag and were corrected in place, verdicts untouched
(ADR-0026, #235); leaving them alone would only have swapped a share inflated by
foreign rows for one deflated by its own.

(Shown wrapped; it is one line in the file. `jq -e . docs/findings-log.jsonl` is the check.)

The schema is also enforced in code: `uv run python -m doug.findings_log check`
(and the pin in `api/tests/test_findings_log.py`). Append at disposition time with
`uv run python -m doug.findings_log append --pr N --layer doug --repo doug --rule …
--verdict disproved|real|adjacent --changed|--no-changed --settled-by "…"`. Rates are
prospective-only (`… rate`); backfill never enters the denominator. Any number
you publish comes from a call scoped on both axes:
`… rate --repo doug --rule-prefix reader:`.

The product path also applies the resolution rule without editing the frozen
prompt (ADR-0012's retained five-constant freeze): after a reader verdict, **missing-import** findings are
settled against runtime imports in the full file at the reviewed head
(`doug/settle.py`). `if TYPE_CHECKING:` imports do not settle (residual-real
per the table above). Dropped findings leave `risk_score` alone and add a
weight-0 `settled-missing-import` reason so a flagged empty-finding check run
is not silent.

The same rule now also covers the **unmigrated-column** / **schema-dependency**
class — 5/5 disproved across PRs 25, 30 (twice) and 48 (twice), see "No
migration for this column…" and "Your disposition is invisible…" above.
`doug/settle.py`'s `drop_disproved_schema_findings` asks the live database
(`store.columns_of`, `inspect(engine).get_columns(...)`) rather than
re-reading migrations.py's diff-touched versions, because that is the check
that actually settled every one of the five — `installations.token_hash`
never appears in any migration at all; it shipped with its table via
`create_all()`. Same weight-0 notice pattern, rule `settled-schema-dependency`.
Deliberately narrow in the same place missing-import is: a claim about a
whole *new table* (not a column on an existing one) is not settled by this
check — a brand-new table introduced by the diff under review is correctly
absent from the live schema, and its disproof is migrations.py's own
convention (new tables arrive via `create_all()`, never a migration), not a
schema lookup.

The third class is the one this section opened with: **the falsifier had
already run** (#307, measured in #232 and on PRs 28, 75 and 198 in the
findings log). `doug/settle.py`'s `drop_disproved_ci_findings` reads the
workflow files and the check runs at the reviewed head
(`doug/ci_evidence.py`, `review.head_ci_evidence`) and settles two claim
shapes against a gate that concluded `success` on that SHA: a JS/TS "unused
import breaks the build / fails lint" claim, when every lint job and every
build job that ran over the file is green; and a Python undefined-name or
NameError claim, when every ruff job that ran over the file is green. The
ruff boundary table above is applied as a veto each — the name must be
written as code beside the claim and read at runtime in the file at head,
must not be bound under `if TYPE_CHECKING:` or declared `global`, the file
must hold no star import (F405 replaces F821 there, and F405 is the rule
star-importing projects ignore), no `noqa` that could have silenced F821,
and no match in the root `.gitignore`; F821 must be selected by the nearest
ruff configuration; and use-before-assignment claims are out of scope. "Ran
over the file" is read from the command itself: `ruff check api/doug` at the
root covers `api/doug` and nothing else, and a flag that could change what
ruff reports (`--select`, `--ignore`, `--config`, `--exit-zero`, …) means
the step states no root. A kind is green only when *every* job running it
is green: a green `web` build says nothing about `console/`. A step with
`if:` or `continue-on-error` is not evidence, whatever its job concluded.
Same weight-0 notice pattern, rule `settled-ci-green`, naming the job that
answered. What the parser cannot read (a job whose `name:` holds an
expression, a reusable workflow, an anchor or merge key, a command form it
does not know) contributes nothing, and nothing keeps the finding. Doug's
own two reads of the PR that built this (#314) supplied nine of these
vetoes; the log rows for that PR say which.

**Doug's own review of PR #49** — the branch that added this filter — found
three real gaps in it before merge, all verified by reproduction rather than
taken on faith (REVIEWING.md's own rule):

1. **`reader:overly-broad-regex-match`**, medium: a whole-table claim mixed
   with an unrelated real `table.column` mention in the same description
   settled on the incidental pair instead of the actual (unresolvable)
   claim. Fixed: `claimed_columns` now returns nothing when a bare
   backtick-quoted name appears anywhere in the description — we cannot
   tell which mention is the real one, so we settle neither.
2. **`reader:unhandled-exception-path`**, medium: `columns_of` had no
   guard around `inspect(engine)` — a transient DB failure would raise
   straight through `score_one` (whose except clauses only name
   `SpendCapExceeded`/`ReaderError`) and crash the review job. Fixed: same
   catch-all posture as `review.head_file_text`, returns None on any
   failure.
3. **`reader:environment-drift`**, low: `columns_of` reads `DATABASE_URL`,
   which is Doug's own ledger database, not a per-target-repo one. Correct
   only because self-review makes the two coincide; degrades safely (not
   wrongly) against a real tenant repo, since a tenant's table names
   essentially never collide with Doug's own — but it is a silent no-op
   there, not a working check, until Doug can reach the reviewed repo's own
   schema. Documented, not yet fixed — no current install exercises it.

`layer` is `doug` or `agent-reviewer` — the two layers this file exists to track, kept
separable so one never speaks for the other. `verdict` is `real | disproved | adjacent`.

Three rules, each of which someone will otherwise get wrong:

- **`adjacent` is not a soft `disproved`.** It is the third category above — wrong as
  stated, right about something nearby — and it is *the valuable one and the easiest to
  throw away*. Two of the entries seeded into the log bought a test each while being false.
- **`changed` is a separate axis from `verdict`, and you need both.** A true finding that
  changed nothing is a re-report of something the code already documents; a false finding
  that changed something found a real gap by the wrong route. Collapsing them into one
  column loses exactly the distinction that makes the log worth keeping, and it would score
  Doug's best mode — *"this code does not justify itself"* — as failure.
- **Backfilled rows carry `"source":"backfill"` and are excluded from every rate.** The
  seeded rows were reconstructed from this file's prose and from `IDEAS.md`, not recorded at
  disposition. They demonstrate the schema; they are not evidence. The denominator starts
  with the first `prospective` row. Same discipline as `verdicts.source` quarantining
  `replay` and `research` from published numbers.

**This is not precision.** ADR-0005 reserves that word for defect prediction and mandates
two tables for it. Whether a finding is *true* is a different quantity from whether it
*predicted a defect* — a finding can be true and worthless, or false and load-bearing. Never
report a rate from this log as precision, and never put the two in the same table.

## A shared commit SHA does not make two delivery paths the same idempotency domain

During App-vs-CI dual-run soak (retired with PR #54), a shared head SHA did not
mean the two paths shared an idempotency domain. The CI `/v1/review` route
deduped with `find_review` (NULL App ids); App webhook deliveries enqueue a job
and `worker.py` deduplicates with
`find_verdict_by_identity(installation_id, github_repo_id, pr_number, head_sha)`.
Cross-instrument dedupe would have destroyed the soak evidence rather than
saving a duplicate read. The dual-run comparison dashboard (`/compare`,
`/v1/comparisons`) that measured that evidence is also gone.

Lasting lesson: before treating a dedupe helper as global, enumerate its
production callers and identify the event identity each caller owns. A
hypothetical route from one delivery mechanism through another is not a current
regression.

The same PR #38 review pass also taught coverage-read lessons that outlive the
dashboard: do not invent `.get()` fallbacks for column shapes the producer has
never emitted; prefer set-based joins over per-verdict SELECTs; and when a
safety bound would cut evidence, fail loud rather than return a partial slice
that a client could misread as a missing path. Trace an error through its
consumer before claiming the user sees a crash or fabricated state.

## New tables never need a migration — only new columns on an existing one do

PR #25 got a medium finding: `deep_read_counters` and `verdicts.prompt_hash` looked
unmigrated, so a deployed database would raise on first use. `store.py`'s own module
docstring disproves half of it (`prompt_hash` already has both a `Table` column and a
migration 001 entry, landed in #18, outside this diff) and the migration mechanism itself
disproves the other half: `migrations.py`'s `MIGRATIONS` list has never once contained a
`CREATE TABLE` — `review_jobs`, `installations`, `installation_repos`, and `outcome_jobs`
all shipped without one, because `create_all()` (called on every `_get_engine()`) adds any
table missing from the target database and only ever fails to add a *column* to a table
that already exists. A migration is for the second case, never the first.

Not a bad finding — a fresh reader has no way to know that convention from the diff alone,
and it bought a real regression test (`test_deep_read_counters_needs_no_migration_on_a_database_that_predates_it`)
that builds a database with every table except the new one and proves `create_all()` still
adds it. Same rule as PR #19's datetime finding: check the surrounding code, then say which
file settled it, in the disposition — here, `store.py`'s docstring plus the absence of any
`CREATE TABLE` anywhere in `migrations.py`.

## "No migration for this column" often means "not in the diff's new versions"

PR #30's high finding: `find_review` / `save_review` now use `verdicts.head_sha`, but "the
visible migration list only adds `prompt_hash` (v2) and indexes (v3)." Disposition: **false**.
Migration **001** has added `head_sha` since #18 (`6a1a213`); this PR only started writing
and querying it. Doug was looking at the *diff's* `MIGRATIONS` delta (new or touched
versions), not the full list, and said so in the coverage line — `Partial read: 50% … Never
sent: … test_migrations.py`.

Same shape as #25's `prompt_hash` half: a column that already has an older migration looks
unmigrated when the reader only sees the versions this PR introduced. Before treating a
missing-migration finding as Critical/High:

1. Read Doug's coverage line (unread `migrations.py` / tests are a stop sign).
2. Open the full `MIGRATIONS` list and search for `ADD COLUMN <name>` in *every* version,
   not only the ones in the diff hunk.
3. Confirm the `Table()` definition and the migration agree — but know how far that guard
   reaches. `test_no_migrated_table_has_a_column_unaccounted_for_by_baseline_or_migration`
   (`api/tests/test_migrations.py:163`) loops `for table in _BASELINE_DDL`, and
   `_BASELINE_DDL` holds **only `verdicts` and `outcomes`**. A new column on `findings`,
   `reads`, or `deviations` is unguarded in both directions: the suite stays green while
   production lacks the column. Add the table to `_BASELINE_DDL` in the same PR that adds
   the column, or the drift test everyone will cite is not watching.

If the column is already migrated outside the diff, say so in the disposition and name the
version + landing PR. Do not add a duplicate `ALTER` "to be safe" — that is noise, and on
sqlite without `IF NOT EXISTS` it depends entirely on `_SATISFIED` text matching.

PR #30's second Doug pass repeated this same high finding after `claim_generation`
(migration 004) was added — still false for the same reason. The coverage line again
cut before the older migration versions. A finding that returns after a disposition
that named the landing migration is not new evidence; re-check the full `MIGRATIONS`
list before reopening it.

## "Post failure loses the check run" must distinguish raise from swallow, and retry from tradeoff

PR #30 ordered `ingest.complete` before `check_run.post` so a lost claim cannot emit a
second check run on the identity-replay path. Doug flagged that as "if the GitHub post
raises or the process dies, the job is already done and never retried — the silent
never-reviewed failure." Disposition: **half-true**.

`check_run.post` **never raises** (ADR-0010: failure is swallowed and logged). The
GitHub-outage path was already "reviewed with no check run" under the old order. What
changed is only the process-death window *between* complete and post: that job will not
retry, while death *before* complete still recovers via reclaim + identity-replay.

That is the intentional tradeoff against duplicate check runs after reclaim. When
disposing an ordering finding against this path:

1. Read `check_run.post` — does it raise, or swallow?
2. Ask which failure the queue can still retry (status still `running`) versus which it
   cannot (already `done`).
3. Name the competing defect the new order closes (here: double post on lost claim).
   Do not treat "ADR-0010 says swallow post failure" as "posting must be ungated by
   queue state" — skipping a post when the claim is lost is not the same as swallowing a
   GitHub error after a held claim.

## A completeness check must be about content that could have been reviewed, not about hitting an API's raw file list

PR #25 also introduced `Coverage.complete` requiring `files_sent == changed_files`, and got
a real medium finding: a PR touching one binary file (a screenshot, a lockfile checksum)
would be marked incomplete forever, because a file with no patch never produces a diff
header and `files_sent` can never count it. The naive fix — drop the check — would have
reopened the exact bug it exists to catch (a 250-file PR silently rendering as fully read).

The right fix distinguishes what GitHub's `DiffEntry` actually tells you: a genuine binary
comes back with `additions == deletions == 0` alongside `patch=None`, because git cannot
count lines in it. A large text file GitHub declines to inline for size still carries the
real line counts it computed. Only the second case is content that should have been
reviewable and was not — `files_dropped` now excludes the first, and `complete` compares
against `files_dropped` rather than the raw `changed_files` count, which was always going to
disagree with `files_sent` on any PR touching a non-text file. `changed_files` stays as a
display fact for the receipt ("N of M"), decoupled from the boolean.

Same shape as the idempotency-pre-read case above: the finding named a real gap and
suggested the wrong repair. The useful move was asking what GitHub's own data can actually
distinguish before picking which files count as "dropped."

## Intentional uniqueness is not a behavior-change defect

PR #43's migration 005 made App-path `(installation, repo, pr, head_sha)` unique so the
published denominator cannot double-count. Doug flagged `reader:behavior-change`: same-SHA
re-scores no longer insert a new verdict row. That is the decision, not a regression — ADR-0011
records it. A finding that restates a locked uniqueness contract as an accidental change
should be dismissed, not "fixed" by re-opening duplicate ledger rows.

## Do not invent schema dependents the unread files would disprove

Same PR, `reader:unsafe-migration` (high): migration 005 deletes duplicate verdicts after
clearing findings/reads/deviations, and Doug warned that "e.g. outcomes" would dangle or
violate an FK. outcomes has never carried `verdict_id`; it joins by identity columns. The
tables that *do* FK to `verdicts.id` are declared in `store.py` — which the coverage line
said was never sent (`Partial read … Never sent: api/tests/test_store.py`). The finding
treated a guessed dependent as fact.

Disposition when this shape appears: read the coverage line first (see above), then check
`store.metadata` foreign keys before expanding a destructive migration. The repair on #43
was a pin of the real closed FK set plus a migration comment, not deleting from tables that
do not reference the row.

## A beyond-ticket finding about a missing decision wants an ADR, not a revert

PR #43 also got unvalidated `beyond-ticket` notes: ADR-0001 had rejected a migration
framework until data-in-flight needed preserving, and the index-not-on-Table convention was
undocumented. Both were decision-record gaps. The right move was ADR-0011 (sanction
destructive constraint prep; name the create_all divergence), not ripping out migration 005
or declaring the unique index on the SQLAlchemy `Table` (which would reintroduce the
divergence migration 003 already refused).

When Doug says the code went past a recorded rejection, either (a) the rejection still
binds and the code is wrong, or (b) the situation the ADR said to revisit has arrived and
the record needs updating. Pick deliberately; do not "fix" (b) by reverting the work that
forced the revisit.

## Two token classes

`DOUG_API_TOKEN` is the **operator** credential: unscoped, reaches every
endpoint, and is what `doug-web` sends server-side (`web/lib/api.ts`). Reviews
that assume "the token" is tenant-scoped are reading the wrong class.

A **tenant** token is dispensed by `POST /v1/installations/token`. Only a
peppered HMAC-SHA256 of its secret half is persisted, in
`installation_tokens.token_hash` — its own table, not a column on
`installations`, because mint appends and one installation can hold several
live keys (MT5). The pepper lives outside the database (`DOUG_TOKEN_PEPPER`)
and is versioned per row, so a DB-only breach yields unusable hashes and
pepper rotation is rolling rather than a flag-day. The row is found by
`token_lookup` — a plaintext key id, safe in logs — never by the hash; the
secret itself is returned once by `mint_key` and is unrecoverable after that.
A key resolves to exactly one `installation_id`, and to a repo selection
re-intersected against the LIVE ledger on every call, so an uninstall or a
removed repo ends access next request (`tenancy.resolve`).

It reaches **two** endpoints, and they are gated by **different** scopes:
`GET /v1/queue` requires `queue:read`, and `GET /v1/prs/{n}/receipt` requires
`receipt:read`. No other endpoint honours a dispensed key at all — the
operator-only routes answer a resolving tenant key with `404` (`_operator_only`),
and key management refuses `X-Doug-Token` outright, because keys cannot manage
keys.

"Tenant-reachable" is therefore not one permission, and a reviewer sizing up
the blast radius of a dispensed key has to read the scope, not the class. A
key holding `queue:read` alone gets `401` from the receipt route — which is
the state every key minted before `8bb0622` is in, and re-minting is what
grants the new scope (append-only, so the existing key is undisturbed).

A route becoming tenant-reachable is a change to that list, and it needs its
own scope checked explicitly rather than an existing one reused: the `scopes`
column exists precisely so a receipts key cannot silently inherit queue
access it was never granted, or the reverse.

Three things a reviewer should check, because each has a failure that looks
fine in passing tests:

1. **Any new filter on `latest_reviews` goes inside the grouped subquery.**
   Outside, an excluded row can still win `max(id)` for its PR and then be
   dropped — the PR vanishes rather than falling back. Pinned by
   `test_scoped_queue_falls_back_to_the_app_row_under_a_newer_ci_row`.
2. **Cross-tenant is 404, never an empty list.** An empty list reads as "no
   reviews yet" and confirms the caller's guess might be real.
3. **New GitHub calls on public endpoints check the caller's credential
   first.** The shared 5,000/hr REST quota was exhausted twice on 2026-08-02;
   a public endpoint that spends Doug's quota before the caller's is a drain
   loop. Pinned by `test_non_admin_pat_never_spends_dougs_github_quota`.

## A table only a webhook populates can be empty in production

Found 2026-08-04, by inspecting the production ledger while chasing an
unrelated finding on PR #48.

`installations` has **one writer** — `api.py:730`, inside the `installation`
webhook handler — and it is read by `worker.reconcile_all` (via
`store.active_installations`) and by `tenancy.mint`/`store.active_repos`.
In production that table held **zero rows**, while `verdicts` held 33 rows
carrying `installation_id = 150424894`. The App path was demonstrably working;
the table describing the installation had simply never been written, because
Doug was installed before that handler existed and no `installation` delivery
was ever replayed.

Every test seeds the row first — `upsert_installation(...)` is the opening line
of the fixtures — so the whole suite passes against a state production is not
in. The green suite is evidence about the code, not about the ledger.

When reviewing anything that reads a table:

1. **Ask who writes it, and whether that writer has definitely run in
   production.** A webhook handler shipped after the event it handles will
   never have fired for installations that predate it. Redelivery is a manual
   act nobody performs by default.
2. **Distrust a passing test whose fixture creates the row under review.** It
   proves the read works given the row; it says nothing about whether the row
   exists. This is the same class as ADR-0002's self-referential test — a check
   that cannot fail in the direction that matters.
3. **Prefer one query against the real ledger to any amount of reasoning about
   it.** The reasoning here — "the table is populated by the webhook, the
   webhook works, reviews are happening" — was individually true at every step
   and wrong at the end.

The symptom this hid: `reconcile_all` loops over `active_installations()`, so
with an empty table the startup sweep enqueues nothing *by construction*. That
had been recorded in HANDOFF as "the webhook path drains jobs promptly, so at
any boot there is nothing pending for the sweep to find" — a plausible
explanation for the right observation and the wrong reason.

## A successor ADR in the PR is invisible to the deployed intent read

PR #56 proposed ADR-0012, superseding ADR-0002's six-constant freeze with a
five-constant freeze plus a coverage-governed `DIFF_BUDGET`. Doug's unvalidated
intent pass repeatedly said no decision sanctioned that change and reported it
as a violation of ADR-0002. The missing mechanism was not in the prose: it was
which Git ref the intent provider reads.

`review.read_intent` calls `intent_providers.fetch(gh, owner, repo)` with no
`ref`, so GitHub serves the default branch. While the PR is open, that branch
still has ADR-0002 accepted and has no ADR-0012. The PR head has the opposite
binding set: ADR-0002 superseded, ADR-0012 accepted. The deployed intent read
therefore cannot evaluate the successor record in the change that introduces
it; `Judged against: ADR-0004, ADR-0002` is a receipt of that limitation.

Do not automatically feed a proposed ADR from the head into the same PR's
policy check — that lets code self-authorize by adding its own decision. Treat
the deviation as a base-policy warning for the human decision maker. Before
calling it a defect, compare the base and head frontmatter, read the check's
`Judged against` line, and verify whether the successor was explicitly approved.
After merge, `intent.select`'s accepted-only filter makes the successor binding
and excludes the superseded record.

## Separate an accepted behavior change from an unmeasured regression

The same PR produced repeated findings that tier ordering and a 100k ceiling
change the model input and could reduce verdict quality. The first clause is
true and ADR-0012 records it as the decision, including the loss of the old AUC
claim. Restating that accepted trade as a behavior-change finding is not a new
defect and should not be "fixed" by restoring alphabetical 30k reads.

Compound performance findings need to be split at the evidence boundary. The
input-cost increase was measured; latency and timeout frequency were not.
`DEFAULT_READ_TIMEOUT_S` and `MAX_TOKENS` staying fixed make a regression
plausible, not observed. Disposition the combined claim as adjacent until a
latency distribution, timeout count, or production fallback rate establishes
the second half.

The same present-versus-future rule applies to concurrency. The historical
backfill was a standalone synchronous script, so no concurrent live reader
shared its process. That made the reported corruption path hypothetical, but
the module-global mutation was still avoidable. The useful change was an
explicit `coverage(..., budget=30_000)` argument, pinned by a test that pauses
the historical call and observes the live global from another thread. Do not
claim a current race without a caller; do not defend unnecessary shared state
when a value can travel as data.

## Test script imports through the entrypoint the repository supports

PR #56's `reader:fragile-import` said `backfill_ledger.py` fails when run from
another working directory because it imports sibling probe scripts by name.
Executing the documented file path from both the repository root and `/tmp`
got through every import and reached the expected `DATABASE_URL not set`
guard. Python places the script's own directory on `sys.path` for that form.

`python -m scripts.backfill_ledger` and `import scripts.backfill_ledger` from
the API root do fail because `scripts` is not a supported package interface;
no production caller uses either form. Do not turn an unsupported invocation
into a runtime defect. If module execution becomes a contract, make the scripts
a package, convert all sibling imports coherently, and add that exact invocation
to the tests rather than patching one import in isolation.

## Keep prospective clock catch-up separate from research backfill

`scripts/backfill_ledger.py` imports research-corpus evidence. The production
`scripts/backfill_outcome_jobs.py` catch-up does something narrower: for a stored
14-day clock belonging to an installation present in the `installations`
registry, it inserts only the missing 60-day sibling from the same merge facts.
Do not transfer the research script's sentinel assumptions or broad write shape
into this prospective denominator repair.

A production clock catch-up is reviewable only when all of these controls travel
together:

- eligibility is structural registry membership, not a guessed installation-id
  range or a research sentinel comparison;
- the anti-join targets the complete outcome identity, and existing pairs are
  rejected when `merged_at`, `base_ref`, or the 60-day `due_at` conflicts;
- a read-only dry-run records the exact missing count, and apply refuses a
  different count;
- an exclusive manifest records the exact inserted identities and verifies that
  every row is still untouched before rollback; and
- the daily Scheduler is proven enabled, paused before apply, and resumed only
  after either verified rollback or audited manual adjudication.

Cloud SQL Studio temporary tables are not a cross-command audit mechanism: its
submissions may use different sessions. Use session-independent violation
queries and the durable manifest in
`docs/design/outcome-loop/60-day-backfill-runbook.md`.

## Deprioritized files are not silently omitted

`features._is_prose` is a routing heuristic: it sends prose after code and
tests, but `read_order` still includes every patch. If the budget lands before
or inside one, `Coverage.files_unseen` or `Coverage.file_cut` names it and the
check run renders that receipt. "May not reach the model" can be true;
"silently never reaches the reader" is false for a file GitHub supplied.

Still verify the classifier rather than dismissing every edge case. PR #56's
earlier passes found real dependency manifests (`requirements.txt`,
`requirements-dev.txt`, `constraints.txt`) falling through the `.txt` suffix;
those now stay code and have regression tests. A later pass supplied the concrete
`CMakeLists.txt`, which was also misclassified by its `.txt` suffix even though it
drives the build. It now has a routing-only exception: adding it to the scorer's
global manifest set would have changed unrelated risk features.

For a new claim, provide a concrete behavior-bearing path, check whether it is
already excepted, and then distinguish a bad classification from the
already-visible cost of an accepted lower tier. Keep a routing repair scoped to
routing unless the scoring taxonomy is independently wrong.

## A count and its denominator must come from the same population

PR #63's facet pills counted runs over the full fetched set, then rendered
that count against a denominator that had already been filtered:
`${option.count} of the ${totalShown} runs shown`. With `?band=flagged`
active the "cleared" pill read "32 of the 37 runs shown" — while every one
of those 37 was flagged, so zero cleared runs were on screen. Filter hard
enough and the numerator exceeds the total printed beside it.

Both numbers were individually correct. Neither was computed wrong. The
defect lives only in their pairing, which is why it survived a green build,
a clean typecheck and 55 passing unit tests: no single function is at fault,
and the types are both `number`.

The generalizable check is to name the population for every rendered
statistic and compare the names, not the values. Here the numerator's
population was "runs in scope" and the denominator's was "runs matching the
current filter"; the labels were the tell, not the arithmetic. When a
component takes a total as a prop, that prop's contract is the population,
so say which one in its type — a bare `total: number` invites the caller to
pass whichever count is nearest.

Doug found this one. Its wording pointed at the summary line rather than the
pill title, and the summary line was correct — "37 of 68 runs" pairs a
filtered count with an unfiltered total and says so. Chase the described
failure to whichever code actually exhibits it before disproving a finding
because the named location is clean.

## A comment claiming a safeguard is a claim the code must be checked against

`facets.ts` documented that "the page suppresses counts entirely once that set
is a truncated page." `FacetBar` never referenced `atCap` and always rendered
counts. The comment described a design that was considered and then not built,
and a test repeated the same sentence — so the claim was asserted twice and
implemented zero times.

This is the "comment that outlives its truth" class, with a sharper edge: the
comment did not describe stale *behaviour*, it described a *safeguard*. A stale
comment about how something works wastes a reader's time. A stale comment about
a protection that does not exist tells the next reviewer the hazard is already
handled, so they stop looking. It also survives review more easily, because a
reviewer who reads the comment and agrees with it has no reason to go find the
enforcement.

Two habits catch it. When a comment says the code refuses, suppresses, rejects
or guards, grep for the mechanism before believing it — the enforcement is a
line of code with a name, and if you cannot find it, it is not there. And when
a safeguard's condition already exists as a named flag, the flag should reach
every component whose output the claim covers; here `atCap` reached the header
and the group badge but not the pill bar, which is precisely where the untrue
sentence was written.

Related: the fix reworded a title from "N runs in scope" to "the newest N runs
fetched". Both the numerator and the denominator had been correct throughout;
what was wrong was the noun naming the population. Statistics get their truth
from their label as much as their arithmetic.
