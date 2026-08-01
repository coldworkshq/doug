# HANDOFF — doug

State:    building — step-2 (GitHub App + webhook ingest) plan is on main,
          reviewed; next session EXECUTES it.
Next:     Execute docs/superpowers/plans/2026-07-31-step-2-github-app-webhook-ingest.md
          task by task (superpowers:subagent-driven-development or
          executing-plans). Read the plan's header first: Tasks 6/7
          interleave deliberately; branch fix/reliability-review collides
          with Tasks 9/10. Execute via PRs (ADR-0008) — the plan document
          itself was pushed to main on Andrew's explicit say-so; that
          authorization does not extend to the implementation.
Blockers: none. Credits topped up 2026-07-31; reader tier live in prod.

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

Decisions this session (2026-07-31/08-01):
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
- Full session state: ../HANDOFF.md on Andrew's machine (project root,
  above this repo) is the richer, hook-maintained handoff.
- In-flight elsewhere: branch fix/reliability-review (worktree
  .claude/worktrees/reliability-fixes) — reliability fixes incl. /v1/review
  idempotency (endpoint dies in Task 9) and gcp.sh traffic gating (merge
  INTO Task 10's version).
- Stale branch workflow-summary-test-fidelity holds ~49 unmerged test lines
  (post-#13 work); decide merge-or-drop deliberately.
- stash@{0} (queue-polish era): dashboard repoint + the lost step-1 plan
  file. Both obsolete (repoint shipped via deploy config; plan content
  landed in #14) — drop deliberately when convenient.
- Carried forward: reader-feedback items 3 & 4 (invariant-vs-mechanism;
  severity = impact × confidence) need a frozen v2 prompt + validation run —
  credits now exist, still unscheduled. lema#643 had FOUR reader findings
  (reader:brittle-test-assertion, low, unscored) — evidence the reader
  reads tests it is given.
