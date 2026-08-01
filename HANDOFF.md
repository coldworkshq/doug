# HANDOFF — doug

State:    building — M0 CLOSED (PR #16 merged 240caf5, deployed; only the
          Andrew-deferred key rotation remains). M1 underway via
          superpowers:subagent-driven-development: plan Tasks 1–2 done and
          review-clean on this branch; Tasks 3–10 pending, PAUSED by
          Andrew after Task 2 (2026-08-01) to land a mid-branch PR.
Next:     Merge the Tasks-1–2 PR, then resume M1 at Task 3 (Queue ops,
          ingest.py). SDD ledger + extracted briefs + the Task 6 amendment
          live in this worktree at .superpowers/sdd/2026-07-31-step-2-
          github-app-webhook-ingest/ (git-ignored — keep the worktree
          until M1 completes). Execution order per plan header: 3, 4, 5,
          7(Steps 1–3), 6, 7(Step 4+), 8, 9, 10. Execute via PRs
          (ADR-0008).
Blockers: none. Credits topped up 2026-07-31; reader tier live in prod.
          One open M0 item, deliberately deferred by Andrew: rotate +
          delete the live local key at
          api/.backtest-cache/llm-probe/api-key (needs Anthropic console
          access neither this session nor the executor has).

Key facts for the executor:
- App: dougs-review, App ID 4450932, installation 150424894 on drewjst
  (User, selected: doug only). Perms checks:write/contents:read/
  pull_requests:read/metadata:read; events: pull_request. Private key in
  Secret Manager doug-github-app-key (no IAM grant yet — deliberate, Task
  10 decides the dedicated-SA custody). Webhook secret doug-webhook-secret
  v2 (v1 has a trailing newline; prod pinned to :2, disable v1 at cutover).
  Webhook verified end-to-end in prod: ping + installation events 202 with
  valid signatures; deliveries currently verify-and-discard (api.py:331).
- Install visibility is "Only on this account" — flip to "Any account"
  before installing on lemahq/lema (Task 10 cutover).
- The plan was built by 3 drafting agents on locked interfaces, reviewed by
  2 adversarial verifiers (both verify by execution), 3 blockers + 5 majors
  fixed. Deepest invariants (do not "tidy" these away): enqueue REVIVES
  failed/superseded rows in place with a STABLE id; drain's seen-set bounds
  both retry burn and the force-push supersede/revive ping-pong; the
  no-ledger 503 is scoped to the three handled webhook events only.
- Derangement check (2026-07-31): BAR FAILED and the instrument is invalid
  for constraint-style records — validates nothing either way. Deviation
  findings stay UNBELIEVED; check-run copy must keep the "unvalidated"
  label. Positive-control experiment needed before further intent-stream
  investment. Full analysis: workspace/research/phase1-entry-preregistration.md
  (workspace/ is untracked — lives only on Andrew's machine).

Decisions this session (2026-08-01, M1 Tasks 1–2):
- outcome_jobs is a store.metadata table, NOT a migration (Global
  Constraint: new tables via create_all; migrations are for columns on
  existing prod tables) — rejected: ROADMAP's literal "migration 002"
  framing for the table.
- installation.created token mint SKIPPED: hash-only storage makes an
  install-time mint unrecoverable dead weight; M2's dispense endpoint
  mints and writes installations.token_hash (column landed in Task 2) —
  rejected: minting a token nobody can ever read back.
- verdicts.source widened to String(64) ('review:<login>' needs 46) —
  rejected: plan's String(20).
- Two plan-mandated defects fixed against the plan's literal code because
  the plan's own stated invariants condemned them: apply()'s version
  insert now swallows the duplicate-version race (docstring: "already
  done is satisfied, not failed"); drift test now pins BOTH directions
  (baseline + migrations == metadata) — rejected: shipping the plan's
  verbatim body over its intent.
- pull_request_review ingest design (for Task 6): tier='external',
  band cleared/flagged from review state, dedup on (inst, repo, pr,
  source, head_sha, scored_at); latest_reviews/find_review must exclude
  tier='external'. GitHub App needs the "Pull request review" event
  subscription — MANUAL step, Task 10 cutover checklist.

Decisions this session (2026-07-31/08-01, M0 pass):
- workflow-summary-test-fidelity: DROPPED, branch deleted (local + remote).
  Its only real content vs main was a test regex fix, already byte-identical
  on main; the branch's sole diff was a stale HANDOFF.md snapshot —
  rejected: merging it (nothing to merge).
- PR #15 was already merged upstream before this session acted on it
  (by a concurrent session); local main fast-forwarded, no rebase needed.
- Intent-stream posture (per-installation flag, default OFF for tenants,
  ON for dogfood, experimental label) needed no new decision — confirmed
  already written into design-lock.md:62 — rejected: re-deciding it.
- Key rotation at api/.backtest-cache/llm-probe/api-key deferred by Andrew
  this session (needs Anthropic console access) — rejected: deleting the
  file without rotating first (would just lose the credential, not retire
  it).

Prior decisions this session (2026-07-31/08-01, step-2 plan):
- Step-2 plan pushed straight to main (Andrew's instruction, sole session);
  execution returns to PRs. — rejected: PRing the plan doc (explicitly
  overridden by Andrew).
- ADR-0003 will be superseded by ADR-0010 (neutral check run) in the same
  commit as the check-run code; ADR-0007 and ADR-0008 get prose corrections
  only (their decisions stand, their surface references die with CI).
- Anthropic key rotation staged create-then-revoke-after-verify (Task 10)
  so the live reader never breaks between rotation and deploy.

Pointers:
- Plan: docs/superpowers/plans/2026-07-31-step-2-github-app-webhook-ingest.md
  (commits d51eec8..94f87e9+). Spec: docs/superpowers/specs/
  2026-07-30-github-app-tenancy-dashboard-design.md (lema mentions
  clarified 2026-08-01).
- Roadmap: docs/design/outcome-loop/ROADMAP.md — the tracking document,
  M0 through M6.
- Full session state: ../HANDOFF.md on Andrew's machine (project root,
  above this repo) is the richer, hook-maintained handoff.
- PR #16 open: docs/outcome-loop-design-lock (design docs + landing-page
  section + .env.example MAGPIE_*→DOUG_* fix).
- stash@{0} (queue-polish era): dashboard repoint + the lost step-1 plan
  file. Both obsolete (repoint shipped via deploy config; plan content
  landed in #14) — drop deliberately when convenient.
- Carried forward: reader-feedback items 3 & 4 (invariant-vs-mechanism;
  severity = impact × confidence) need a frozen v2 prompt + validation run —
  credits now exist, still unscheduled. lema#643 had FOUR reader findings
  (reader:brittle-test-assertion, low, unscored) — evidence the reader
  reads tests it is given.
