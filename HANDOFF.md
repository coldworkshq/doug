# HANDOFF — doug

State:    building — M0 CLOSED. TASK 10 IS DONE: the App path is LIVE and
          verified in production on drewjst/doug (neutral check run,
          "Cleared · risk 0.02 · diff read", on PR #33 — tier in the title,
          so it was a real read and not a deterministic fallback). M1 code
          is complete except TASK 9, which is now the last M1 task. ONE PR
          PER TASK (Andrew's call, 2026-08-01: more Doug verdicts + smaller
          diffs Doug can actually read whole). Merged to main: Tasks 1-2
          (#18), 3 (#19), 4 (#20), 5 (#23), 7a Steps 1-3 (#24, + the #26
          cooloff fix), 8 (#22, ADR-0010), 6 (#27, the webhook rewrite),
          7b (#28, startup sweep + the review-state casing fix — which
          CLOSES Task 7), #29 (the late #24 re-review), 10 (#32, code) with
          the operator cutover run 2026-08-01, and #34 (m1-cutover-done),
          which is main's HEAD — so the paragraph below describes shipped
          code, not a branch still waiting to land.

          #34 (m1-cutover-done) was not a plan task. The cutover
          exposed that worker.process_job wrote NOTHING to the log on any
          successful outcome, so "the review ran" and "the job was never
          claimed" were indistinguishable — answering "did that review
          actually run?" took four tool calls, a dashboard fetch and a
          browser screenshot. It adds one line per outcome, and the fresh
          review and the idempotent replay are worded so they can never be
          confused: only the fresh one says "paid read", because only it
          bought one. See the decision below for why that distinction is
          the change rather than a detail of it.
Next:     A SOAK on the live App path, then M1 Task 9. Task 9 (retire the
          CI token path: delete .github/workflows/doug-review.yml and
          /v1/review) is unblocked and code-ready, and is deliberately NOT
          the next thing anyone does. Andrew's
          call, 2026-08-02: the CI path and the App path run in PARALLEL
          until the App path has been watched against an independent
          reviewer, because Task 9 deletes that reviewer. Exit criteria are
          counted in PRs, not days — see the soak decision below, which
          also carries the reason and the concurrent UI work reading the
          same rows. That decision supersedes nothing about the 10-then-9
          resequencing; it adds a gate in front of the 9.
          Land score-read-auth first (m1-cutover-done already landed, #34).
          Rebase vs. merged #15 still to be done deliberately. AFTER the
          soak and Task 9, M1's exit gate is checkable end to end and M2
          (spend caps) starts — its `[~]` primitive (store.record_deep_read,
          #25) is still wired to no call site, so spend is uncapped in
          production TODAY, which matters more now that the App path is
          the live one.

          What the cutover actually put in production, verified on the
          serving revision: doug-api runs as its OWN service account
          doug-api-sa (not the default compute SA, which holds
          roles/editor on doug-prod0); DOUG_GITHUB_APP_ID and
          GITHUB_APP_PRIVATE_KEY are both in --set-secrets, so
          app_auth.enabled() is TRUE in prod for the first time;
          --no-cpu-throttling is set, without which the background drain
          is suspended the moment its request returns; and Task 7b's
          startup sweep runs at boot, which needs both of those at once.
          doug-web STILL runs as the default compute SA — held back
          deliberately so a misconfigured web SA could not confuse the
          cutover — and gets its own SA in a follow-on PR.
Blockers: none for code. One thing only Andrew can do, and one loose end:
          - subscribe the App to the "Pull request review" event before
            Task 6's third-party ingest receives anything (handler is
            inert but fully fixture-testable until then). STATUS NOT
            RECONFIRMED since the cutover — check the App settings rather
            than assuming the cutover checklist reached it.
          - key rotation is DONE and verified (see below); the loose end is
            that doug-anthropic-key version 1 is still `enabled` in Secret
            Manager, so the superseded material is still readable there.
            Disabling it is separate from revoking the key at Anthropic.

Execution model (do not rediscover this):
- One PR per task. Doug reviews each (ADR-0008); read its findings, but
  VERIFY before fixing or dismissing — roughly half are disproved by files
  outside the diff. See docs/REVIEWING.md, which is the accumulated
  lessons from ~20 findings across two review layers.
- Per task: fresh implementer subagent from an extracted brief, then an
  INDEPENDENT reviewer, then a fix round, then a scoped re-review. Do not
  let the implementer grade its own work, and do not fix findings in the
  controller session.
- Extract a brief with sed from the plan; never make a subagent read all
  4591 lines. Task line ranges: T6 2638-3395, T7 3396-3716 (Step 4 starts
  at 3267 of that slice), T9 4025-4244, T10 4245-4591.

Standing rules this branch learned the hard way:
- A docstring asserting a durability/ordering/concurrency property must be
  TRUE. Eight separate findings here were comments promising guarantees
  the code did not make. If nothing enforces the claim, the comment is the
  bug.
- Plan INTENT governs over the plan's literal code sample. Several samples
  violated constraints the same plan states in prose. Fix it, and record
  the ruling in the PR body rather than applying it silently.
- A test that cannot fail when its named behavior regresses is an
  Important finding. Two shipped tests here were vacuous; both were caught
  by mutation, not by reading.

Key facts for the executor:
- App: dougs-review, App ID 4450932, installation 150424894 on drewjst
  (User, selected: doug only). Perms checks:write/contents:read/
  pull_requests:read/metadata:read; events: pull_request. Private key in
  Secret Manager doug-github-app-key — Task 10 SETTLED the custody
  question: it is granted to the dedicated doug-api-sa, not to the default
  compute SA. Webhook secret doug-webhook-secret v2 (v1 has a trailing
  newline; bound as :latest, which IS v2 — this file once claimed it was
  pinned to :2 and that was never true). Webhook verified end-to-end in
  prod: ping + installation events 202 with valid signatures. Deliveries
  no longer verify-and-discard — Task 6 (#27) dispatches them, and since
  the 2026-08-01 cutover that is what production is actually running: the
  discarding revision is gone.
- Install visibility is "Only on this account" — flip to "Any account"
  before installing on lemahq/lema (Task 10 cutover).
- Carried forward for the doug-web SA follow-on, verified during Task 10's
  scoping and still true of doug-web: the default compute SA holds
  roles/editor on doug-prod0, and roles/editor does NOT include
  secretmanager.versions.access. So the explicit secretAccessor bindings in
  api/deploy/gcp.sh:88-98 are LOAD-BEARING, not belt-and-braces, and the
  gcp.sh:84-87 comment saying so is accurate as written. Do not "simplify"
  those bindings away on the assumption editor covers them.
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

Decisions this session (2026-08-01/02, cutover + the logging it exposed):
- TASK 9 WAITS FOR A SOAK (Andrew, 2026-08-02). The CI path and the App
  path run in parallel on purpose, so the new path can be compared against
  an INDEPENDENT reviewer before the old one is deleted. The reason is the
  App path's characteristic failure mode: SILENCE. Nothing turns red, no
  job fails, no alert fires — the check run simply never appears, and an
  absent check run looks exactly like a PR nobody pushed to. The CI job
  summary is the second, independently-triggered observer that would make
  that visible, and Task 9 is what deletes it, so it goes last.
  Note this is a different claim from the logging work above: that logging
  makes a review the operator ASKS about answerable in one grep. It cannot
  reveal a review that was never triggered, because the missing line and
  the un-triggered job are the same absence. Only a second path scoring
  the same PR can.
  EXIT CRITERIA — counted in PRs, not days. All four:
  1. a PR with MULTIPLE PUSHES (exercises supersede + re-enqueue),
  2. a COLD START whose startup sweep enqueues >0 jobs — it has only ever
     logged 0 in production, so the backstop has never actually done
     anything and is currently an untested claim, not a verified one,
  3. a MERGE that writes an outcome_jobs row,
  4. ~10 CHECK RUNS with none missing.
- A SECOND SESSION is concurrently building the dual-run comparison UI in
  web/, on branch dashboard-dual-run. It owns web/**, api/tests/test_api.py
  and api/tests/test_store.py, and appends only in api/doug/api.py and
  api/doug/store.py. What makes the comparison possible, and is NOT obvious
  from the schema: both current App and CI paths write head_sha as shared
  commit identity for idempotency. App alone also writes installation_id and
  github_repo_id. Current CI therefore has both App ids NULL and head_sha
  populated; legacy CI rows may have all three NULL. The comparison separates
  paths by the App id pair after the store predicate qualifies a row, and
  excludes either one-id shape, both App ids without a head SHA, and
  tier='external'. `/v1/review` replay is scoped to the same null App-id pair,
  so an App verdict cannot suppress the independent CI measurement. A legacy
  row with no head remains visible as neutral, unpairable evidence; it cannot
  establish that either path is missing.
- A FRESH REVIEW AND AN IDEMPOTENT REPLAY MUST NOT LOG ALIKE. They agree on
  every field either line could carry — repo, PR, head SHA, tier, band,
  score, verdict id — and differ in exactly one thing: the fresh one bought
  a model read and the replay re-rendered a row already in the ledger. So
  the difference has to live in the WORDING or it does not exist: one line
  covering both would make spend unauditable from the logs, with an
  operator counting reviews counting replays that cost nothing. Only the
  fresh line says "paid read" — rejected: a single "job N complete" line,
  which is what "add a success log" naturally produces and is worse than
  the silence it replaces.
- The fresh line is emitted BEFORE ingest.complete, not after. By that
  point the read is paid for and the verdict durable, and complete()
  raising is the one failure that re-pends a job in exactly that state — it
  must not be able to erase the record of what the attempt cost. It is
  still not a complete spend ledger (a read dying before save_review
  commits leaves only drain's failure line) and the code says so rather
  than claiming a guarantee it does not make.
- Key rotation CLOSED and verified rather than trusted: the plaintext
  api/.backtest-cache/llm-probe/api-key is gone (whole llm-probe/ directory
  with it) and doug-anthropic-key has a v2 created 2026-08-02. v1 still
  enabled — recorded as a loose end, not ticked away.
- ROADMAP's Task 10/Task 9 item SPLIT into two boxes. One box covering two
  tasks cannot record that one is done and the other is not — rejected:
  ticking the combined line, which would have read as Task 9 being done.

Decisions this session (2026-08-01, M1 Tasks 6–7b):
- Task 9 RESEQUENCED AFTER Task 10 (Andrew, 2026-08-01): Task 9 deletes
  .github/workflows/doug-review.yml, which is the surface producing Doug's
  reviews on this repo today. Deleting it before the App's check run is
  verified working in production would leave every PR — including the ones
  fixing that — reviewed by nothing, with no fallback to roll back to —
  rejected: the plan's 9-then-10 order.
- Task 7b tested the lifespan wiring the brief shipped untested. The brief's
  own note ("both guards are off in tests, so TestClient never spawns the
  thread") describes the gap rather than justifying it; the tests patch
  app_auth.enabled/store.enabled instead of the env behind them, and the
  thread is named so "no thread was started" is assertable rather than a
  race — rejected: shipping Step 4 with the coverage the brief specified.

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
