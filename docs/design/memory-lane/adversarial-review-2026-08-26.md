# Adversarial review — Stage-0 memory ADRs (2026-08-26)

Artifact: coldworkshq/doug branch memory-adrs, docs/decisions/ADR-0022/0023/0024 + ADR-0006 amendment, frozen at ece6ffd.

Filed 60 · fatal/high 38 · adjudicated 38 · survived 11 · refuted 27 · confirmed fatal 1

Not checked: 0 (every refuter returned with evidence). Below threshold, not adjudicated by design: 22 medium/low.

One refuter (ref-skiplocked) adjudicated two ids filing the same premise (abandonment-3, correctness-1) — counted as two adjudications, one agent.

One verdict was internally inconsistent: security-4 returned refuted=true with amended severity high and a required amendment; counted as refuted per the field, its residue (FORCE RLS + security_invoker views) applied as a correction.


## Survived (11)

- coupling-1 — filed fatal, stands at high: join on (github_repo_id, pr_number, merge_commit_sha); memory.tenant_installations history table; drop installation_id from derive_jobs UNIQUE
- coupling-3 — filed fatal, stands at fatal: reads take status set AND force set; provider passes {accepted}x{settled}; fixture pins accepted+advisory absent; IntentDoc has six fields incl. required ref; exit bar = status and force filtering
- coupling-5 — filed high, stands at medium: occurred_at per provenance kind = instant sha reached default branch; tiebreak doc>pr>idempotency_key; diff-derived same-subject as link fact not second settled record; reconcile MS-7 SUSPECTED
- coupling-6 — filed high, stands at medium: derive insert lives in store.enqueue_outcome_jobs same tx (webhook + reconciler); four-column key; backfill enumerator = reconcile_outcomes with lookback param; test every 14d outcome row has derive sibling
- coupling-7 — filed high, stands at medium: name tenant producer (doug-api emits tenant.installed keyed on account.id); store refuses events with no tenant; provisioning endpoints part of frozen wire; conformance fixtures include idempotency_key vectors
- security-5 — filed high, stands at medium: tenant_id store-resolved (wire carries installation_id+github_repo_id; store refuses body naming tenant_id); wire is authenticated IAM surface; registry binds producer identity to event_types; /internal/embed accepts store service identity only; mechanism to MS row
- abandonment-7 — filed high, stands at medium: delete claim Gate A supplies memory.jobs measurement; name policy owner/home (store deploy); Stage-1 exit: policy exists and fired once against stalled job
- correctness-2 — filed high, stands at high: App transfer preserves installation ids; REPO transfer re-homes under different installation+account (#227); model memory.tenants + mutable memory.tenant_repos(tenant_id, github_repo_id) link mirroring doug installation_repos; key rows on github_repo_id; 'one UPDATE' true only for reinstall; cite #227
- correctness-3 — filed high, stands at high: add session{harness, external_session_id, seq} variant; force map per variant; add or strike thread/issue/discussion variants; reconcile MS-5; state whether registering a reserved variant is additive
- conformance-1 — filed fatal, stands at high: same defect as correctness-3; pick (A) extend sum type + registry-additive variants, or (B) strike session adapter as direct producer, non-commitment material lives in doug session tables, reaches memory.events only as link on correlated commitment; give decision.dismissed a schema; note doc as addition to MS-5
- conformance-4 — filed high, stands at high: M6 recovery surface = versioned view over the doug schema's review judgments (verdicts/findings) or additive review.judgment event family emitted by Python — §B3 wording; normalizer input is otel.span, an IntentDoc view fails loudly; decisions-ingest if wanted is a separately marked second surface; file drift issue plan §1 vs §B3

## Refuted (27)

- coupling-2 — filed fatal, refuted (residue medium): wording gap: name github_repo_id in provenance; producer holds repo_id (api.py:2519)
- coupling-4 — filed high, refuted (residue low): at-HEAD provider stays primary until parity; residual: name doc-lane trigger in ADR-0024
- security-1 — filed fatal, refuted (residue low): scenario is stated design; residual wording: sanctioned = under governance; drive-by = non-commitment source; retraction via later HEAD commitment
- security-2 — filed fatal, refuted (residue medium): no fork gate on merges (contradicts prereg §2.4); residual: bind drain to reader._charge(scope), max_attempts, injection goldset
- security-3 — filed fatal, refuted (residue medium): neither ADR claims RLS ports; FORCE RLS alone closes owner bypass (probe); residue: write FORCE RLS + SET LOCAL + non-owner runtime role (coldworks 001_init.sql precedent)
- security-4 — filed fatal, refuted (residue high): INCONSISTENT verdict: refuted=true but amended high with required amendment; probe reproduced owner-view bypass on PG 18.4; M6 has no Postgres reader (span file); residue: security_invoker on memory.v*_ views + FORCE RLS + catalog test; public tier from public repos only
- security-6 — filed high, refuted (residue low): no producer ingests threads/issues in Stage 0-2; delimiter is a Stage-4/5 surface rule; optional: tier table is classification not ingest grant
- security-7 — filed high, refuted (residue low): no push producer; docs read at HEAD via contents API; residue clause: occurred_at is GitHub-clocked (merged_at / pushed_at), never git dates; refuse occurred_at > recorded_at + slack
- security-8 — filed high, refuted (residue low): force is pure fn of provenance; diff never persisted; residue: closed write-side schema (DisallowUnknownFields precedent), max_payload_bytes, span rune cap (lema 240), record.redacted event, 'nothing deleted by supersedence'
- abandonment-1 — filed fatal, refuted (residue low): select() RELATIVE_FLOOR excludes ADR-0006 at 0.333; reader reads main not branch; blockquote self-labels not-in-effect; precedent 0012/0018 landed pointer at acceptance; residue: soften ADR-0022 'cannot produce a finding' or hold blockquote to acceptance PR
- abandonment-2 — filed fatal, refuted (residue medium): roster = verdicts.source namespace graded by prereg §7; save_external_review precedent for score-less reviewer; residue: gloss roster in ledger terms in ADR-0022
- abandonment-3 — filed fatal, refuted (residue medium): shared refuter with correctness-1; lema jobs claim by CAS, no SKIP LOCKED; harm unreachable (Python drain already SKIP LOCKED); residue: fix ADR-0024 Context misattribution + memory-store.md:79,:114
- correctness-1 — filed high, refuted (residue medium): same as abandonment-3
- abandonment-4 — filed high, refuted (residue medium): bars live in separate byte-frozen prereg per repo convention; residue: 'is pre-registered' → 'will be pre-registered in <named file>, Andrew-signed before first graded derivation'; ADR-0095 = labeled fixture floor (22 FP/19 TP)
- abandonment-5 — filed high, refuted (residue low): eval is Gate B (Stage 0), before Stage 1 code; lema precedent misdated; residue: ADR-0023 cite Gate B/R2 so 'dark until eval' reads eval-before-seam
- abandonment-6 — filed high, refuted (residue low): 07-31 instrument ruled INVALID for constraint records; re-run would be null; positive-control redesign needs founder prereg; residue: add Gate B clause to ADR-0022 gates; file tracking issue
- abandonment-8 — filed high, refuted (residue low): ADR-0083 recoverable (lema git b2a9ffed, .lema/decisions.jsonl.retired:77); #20 tracks publication; residue: one Consequences line naming source + Stage-1 exit item
- operations-5 — filed high, refuted (residue low): stamp needn't cross the wire (natural-key join; outcome_backfill manifest precedent); created_at partitions dark rows; residue: say drain-on step stamps pending rows before first claim; key rule excludes batch_id
- operations-4 — filed high, refuted (residue low): 'all of it ports' antecedent is jobs+migrations, not RLS; lema idiom cited is the fix not the bug; coldworks invariant 4 is the known port target; residue: one line in ADR-0022 citing coldworks invariant 4 (tx-scoped set_config, FORCE, separate runtime role); MS-4/MS-6 verifier additions
- operations-1 — filed fatal, refuted (residue low): Gate A policies are named; SweepOrphans/reclaim_stalled precedents re-examine on boot; replay contract; residue: 'parked' is a non-terminal memory.jobs status re-claimed at drain start; parked rows count toward oldest-pending-age
- operations-2 — filed fatal, refuted (residue low): githubkit auto_retry=True sleeps on 403/429; 3,000-PR backfill unreachable (rows from webhook only); residue: drain runs behind review claim loop, bounded rows per pass
- operations-7 — filed high, refuted (residue low): cap sum already exceeds 25 today; drain uses doug-api's pool; MS-4 owns pool caps; residue: build-order verifier (SHOW max_connections receipt), not ADR text
- conformance-5 — filed high, refuted (residue low): ADR defers sequencing to the plan; #20 already Gate-B-blocked; four independent controls; residue: append 'and Gate B' to the Gate A consequence line
- conformance-3 — filed high, refuted (residue low): ADR-0010 already amended by ADR-0014 (c8da9d7); deviation section mirrored today; PATCH doesn't notify; residue: editorial sentence noting the mirror; fix doug.md:202
- operations-3 — filed high, refuted (residue low): no 6h reconciler exists; startup reconciler enqueued 0 windows in 102 runs (merge_commit_sha null on pulls.get); same wording gap as coupling-6 (insert lives in enqueue_outcome_jobs; two meanings of backfill). NEW FACT: reconciler heals nothing today
- conformance-2 — filed high, refuted (residue low): ref is dead data (no consumer; review.py:540 uses d.id); provider builds field-by-field; residue: say IntentDoc has six fields, ref provider-derived from provenance; 'changes nothing' → provider maps provenance→ref and applies force filter explicitly (pydantic drops unknown force); four-column key wording; window_days
- operations-6 — filed high, refuted (residue low): executor is Stage-2 gcp.sh choice; claim columns are house pattern, additive; residue: one sentence naming a scheduled Job + claim columns; 'A derive worker ships dark'

## Method

Fan-out size of the `adversarial-review` skill: six attackers (correctness,
coupling, security, operations, conformance, abandonment), one lens each,
fresh context, read-only, at most 10 findings each, against the frozen
artifact (sha256 recorded before the first attacker spawned and re-verified
before the cure). One fresh refuter per fatal/high finding, default
`refuted=true`, required to check the real systems (this repository, lema at
`lemahq/lema`, `lemahq/lema-mcp`, coldworks, GCP via read-only gcloud) and to
cite file:line or command output; a verdict with no evidence would have
counted as "not checked," never as refuted. Medium and low findings were not
adjudicated; their ids are in the per-lens ledgers.

Cures were applied only for survivors. Refuted findings did not change the
artifact, with one class of exception: where a refuter confirmed a factual
error in the draft (a wrong number, a misattributed mechanism, a wrong issue
number), the error was corrected and is listed in the cure commit as a
correction, not a cure.

Not checked by design: lema's test suite was not run; no GCP resource was
provisioned; the 2026-08-19 design pass's own 43 findings were treated as
locked context, not re-adjudicated.

## New facts surfaced by refuters (true today, independent of the ADRs)

- The startup outcome reconciler has enqueued zero windows in 102 runs over
  30 days because `pulls.get` returns no `merge_commit_sha` for this
  repository's merges (`worker.py:1344-1356`). Gate A's "one healing run"
  will be the first time the shared path is exercised. (operations-3)
- `IntentDoc.ref` has no consumer anywhere in `api/doug`; deviation findings
  carry `d.id`. Cleanup candidate. (conformance-2)
- The 2026-07-31 derangement instrument was ruled invalid for constraint-style
  records; re-running it would be a null result. What is owed is a
  positive-control redesign, founder-pre-registered. No tracking issue exists.
  (abandonment-6)
- `doug-ledger` is `db-f1-micro` (max_connections 25) and today's client
  pool caps already sum past it; nothing has hit the wall because
  transactions are short. MS-4 should carry a `SHOW max_connections` receipt.
  (operations-7)
