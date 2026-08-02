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

## A finding that depends on code outside the diff must say so

Doug reviews a diff, not a repository, and it reports two kinds of finding without
distinguishing them: things the diff proves, and things the diff merely permits. Two of its
five findings on PR #19 were the second kind — a datetime aware/naive concern that
`store.py` disproves (every column is `DateTime(timezone=True)`), and a duplicate-read
concern that `worker.py`'s head re-check answers.

Neither was a bad finding; both were unresolvable from what it was shown. Check the
surrounding code before fixing or dismissing, and record which one it was. The same rule
binds agent reviewers, who should mark these ⚠️ rather than assert them.

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

Every verdict carries what was actually read: `Partial read: 83% of the diff (30,000 of
35,956 chars). Cut inside api/tests/test_ingest.py. Never sent: ROADMAP.md.` A clear on a
partial read is not evidence about the unread part, and Doug says so itself.

This is also a PR-size signal pointing the same way as one-PR-per-task: a diff small enough
to be read whole produces a verdict worth something. A 36k-char diff does not.

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
