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
