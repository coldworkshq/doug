# Step-2 amendments (2026-08-01)

Additions to `2026-07-31-step-2-github-app-webhook-ingest.md`, decided during execution and
folded in at their task rather than as a second pass. The plan governs everywhere these are
silent. Tasks 1–5 and 7a are done; what remains below is **Task 6**.

Recorded here rather than in a session workspace because the workspace is git-ignored and
these are requirements, not notes.

---

## Task 6 — clock-start branch (the outcome loop's ignition)

`closed` joins the handled set with its **own** dispatch branch. It must never enter
`PR_ACTIONS` / review-enqueue — a merge must never buy a model read (the plan pins this
itself: "closed must not buy a read").

**`closed` with `pull_request.merged == true`** inserts ONE `outcome_jobs` row:

| column | value |
|---|---|
| `installation_id`, `github_repo_id` | payload ids, never parsed from names |
| `pr_number` | payload |
| `merge_commit_sha` | payload `merge_commit_sha` |
| `merged_at` | payload timestamp |
| `base_ref` | `pull_request.base.ref` |
| `window_days` | 14 |
| `due_at` | `merged_at` + 14 days — **computed from the payload timestamp, not the wall clock** |
| `status` | `pending` |

On conflict with `uq_outcome_job`: do nothing. That unique key **is** the redelivery dedup,
and it is the integrity of the published denominator — see `design-lock.md`.

Only the 14-day row at webhook time; 60-day rows arrive later via a backfill, not here.

**`closed` with `merged == false`** writes nothing at all.

Tests to pin (name them for the guarantee, not the mechanism):
- the same `closed` delivery twice → exactly one `outcome_jobs` row
- `closed && merged` → an `outcome_jobs` row AND zero `review_jobs` rows / zero enqueue calls
- `closed && !merged` → zero rows anywhere

## Task 6 — `pull_request_review` ingest (the neutral-grader lane)

New handled event `pull_request_review`, action `submitted` only. States `approved` and
`changes_requested` produce a row; everything else (`commented`, dismissals) is ignored —
no stance, no row.

Row shape — a verdicts-ledger row, with **no scoring code on the path**:

- `tier='external'`, `score=0.0`, `threshold=0.0`
- `band='cleared'` for approved, `'flagged'` for changes_requested — Doug's own band
  vocabulary is what makes third-party stances adjudicable in the same ledger
- `scored_at` = `review.submitted_at`; `source` = `'review:' + review.user.login`
  (`verdicts.source` is String(64) for exactly this)
- `head_sha` = `review.commit_id`; ids from the payload; `repo` = full_name, display-only
- `raw` = a small dict with the review's id, state, submitted_at (provenance)

No model call, no metering, no check run, no fork gate — nothing is spent. Bot reviewers are
ingested like anyone else; grading bot reviewers is the point of the neutral-grader lane.

Dedup: existence check on `(installation_id, github_repo_id, pr_number, source, head_sha,
scored_at)` — identical for a redelivery, different for a genuine approve→changes-requested
sequence on the same head (append both; the ledger is append-only dated claims).

**Read-helper guard:** `latest_reviews` and `find_review` must EXCLUDE `tier='external'`
rows. External rows carry no findings or coverage and must never displace Doug's own verdict
in `/v1/queue` or in replay lookup. Pin it: land an external row for a PR that has a Doug
verdict → `latest_reviews` still returns Doug's row.

**Operational note for Task 10's cutover checklist:** deliveries only arrive once the GitHub
App is subscribed to the "Pull request review" event — a manual App-settings step. The
handler is inert, and fully fixture-testable, until then.

## Task 6 — NO token mint

Contrary to one line in ROADMAP M1's original wording: do **not** add an
`installation.created` token mint. Hash-only storage makes an install-time mint
unrecoverable dead weight; M2's dispense endpoint mints and writes
`installations.token_hash` (the column shipped in Task 2). This item exists so it does not
get re-added.

---

## Task 7 — reclaim wiring (done in 7a, recorded for the record)

`reconcile_all()` calls `ingest.reclaim_stalled()` once, **before** the enqueue sweep, in the
startup path only — never inside `reconcile_installation`, because the sweep is queue-wide
and a per-installation call would touch other tenants' rows as a side effect of one
installation's event.

Ordering is not cosmetic and the equivalence is not real: `enqueue`'s supersede filters
`status == 'pending'`, so it cannot flip a still-`'running'` zombie. With a stranded job at
one SHA and a force-push to another, reclaim-first ends `{stale: superseded, new: pending}`
while sweep-first leaves the stale SHA alive as work a worker must claim and discard.
