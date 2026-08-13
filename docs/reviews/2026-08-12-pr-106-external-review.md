# External review vs Doug — PR #106 @ 616ff99

A calibration record for Doug's self-improvement loop: what an external
medium-effort review (8 finder angles, 1-vote adversarial verify) found on
this PR, next to what Doug's own check run flagged on the same diff.
Machine-readable table first; the narrative deltas below are the training
signal.

## External findings (all verified, all fixed in 067e8ff)

| # | file:line | category | finding | doug caught it? |
|---|-----------|----------|---------|-----------------|
| 1 | api/doug/check_run.py:176 | correctness | Footer joined to body with one `\n`; GFM lazy continuation glues it into the last bullet — the PR's two instrument lines never render as their own block | no |
| 2 | api/doug/check_run.py:86 | correctness | Meter renders against cap 200 but spend is enforced at 4000, so public surfaces can show `deep reads 201/200` | no |
| 3 | api/doug/store.py:1361 | correctness | `review_jobs` fallback: unordered `LIMIT 1`, no prefer-with-jobs — can publish a 0/0 scoreboard for a repo with adjudications | no |
| 4 | api/doug/worker.py:473 | correctness | `_instrument` unguarded at render time; transient DB error after the paid read burns attempts and loses the check run | partial (`per-job-db-query` saw the queries, not the failure mode) |
| 5 | api/tests/test_deploy_gcp.py:158 | test-coverage | Promote-gate test weakened needlessly; `count >= 1` vacuous; openapi+queue unpinned from the gate | no |
| 6 | api/doug/api.py:2278 | reuse | Bot-author predicate hand-copied at four sites in three shapes | no |
| 7 | web/lib/api.ts:112 | reuse | Scoreboard fetch-cache is a token-level copy of the queue's; backend endpoint scaffold likewise | no |
| 8 | api/doug/store.py:1288 | efficiency | Snapshot ran 3 sequential SELECTs + meter; one filtered aggregate reads one consistent snapshot | partial (same site, cost framed as "unindexed scans" — wrong: `uq_outcome_job`'s leading columns serve the predicate) |

## Doug's findings, dispositioned

- `behavior-change-silent-skip` — by design (Approach A); the no-override
  observation is a roadmap note, not a defect.
- `cache-key-mismatch` — sharp version (test-order fragility) empirically
  refuted: monkeypatch teardown restores the slot; single-slot design is
  deliberate and test-pinned on the queue. Warm-process env flip is real
  but env changes only at restart, which empties the cache.
- `deploy-gate-dependency` — mostly pre-existing (queue already on the
  promote line with the same 404-if-unset contract). Real kernel: the
  scoreboard also 404s when the snapshot resolves None, so a pinned repo
  with zero history — a fresh environment — fails its first deploy at the
  scoreboard smoke where the queue serves an empty 200.
- `truncation-edge-case` — unreachable: reserved tail ≈ 220 chars vs
  SUMMARY_LIMIT 60,000.
- `per-job-db-query` — real site, see rows 4 and 8; cost misattributed.

## Deltas worth encoding

1. Doug read the diff but never rendered it: the two most valuable bugs
   (rows 1–2) are only visible when the output surface is actually
   produced — markdown semantics, display-vs-enforcement mismatches.
2. Doug flagged plausible-sounding mechanisms without executing the
   refutation step (cache test fragility, truncation edge) — both die to
   one concrete check.
3. Doug did not trace cross-file: cap constants (200 vs 4000), fallback
   vs candidates branch asymmetry, test-assertion strength vs the script
   it pins.
