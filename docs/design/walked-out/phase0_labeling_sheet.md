# Phase 0(b) — Bar B labeling sheet (Andrew)

For each unit the cited file's diff is byte-unchanged between the two reads,
so the locked rule carries the finding forward. Mark `addressed: yes` only if
the defect was in fact addressed anyway (fix landed elsewhere, defect gone at
the later head). Bar B passes at <= 1 of 26 addressed. `#75` deploy-ordering is
pre-declared as the expected member.

## 1. PR#38 `api/doug/store.py` [reader:idempotency-scope-change]
- pair 1020->1022, 05fafe2b3c..c8383dc3fc
- finding: find_review now requires installation_id and github_repo_id to be NULL, so any App-written verdict no longer suppresses a /v1/review rescore for the same commit. This doubles LLM spend for commits reviewed by both paths and can produce duplicate ledger rows if any App-originated call ever routes through /v1/review.
- addressed: 

## 2. PR#38 `api/doug/store.py` [reader:fail-loud-cap]
- pair 1020->1022, 05fafe2b3c..c8383dc3fc
- finding: comparison_reviews raises ComparisonResultTooLarge (HTTP 413) when a repo/PR window exceeds COMPARISON_RUN_LIMIT=500 rows; a busy repo with many duplicate verdicts can make /v1/comparisons permanently error for the default limit=50, with no automatic fallback in the dashboard.
- addressed: 

## 3. PR#38 `api/doug/store.py` [reader:unbounded-subquery-scan]
- pair 1020->1022, 05fafe2b3c..c8383dc3fc
- finding: The group-by over all verdicts (max(scored_at) per repo/PR) with an outer join over the whole reads table per verdict has no time bound; on a large ledger this read can be slow without an appropriate index.
- addressed: 

## 4. PR#39 `api/doug/reader.py` [reader:removed-public-function]
- pair 1029->1031, 2cf9cbfe39..4408925d25
- finding: `reader.intent_enabled()` and `intent.enabled()` were deleted and replaced by `enabled_for()`. Any other call sites (CLI, probes, worker, docs scripts) not shown in the diff would raise AttributeError/ImportError at runtime.
- addressed: 

## 5. PR#39 `api/doug/reader.py` [reader:strict-parsing-fallback]
- pair 1029->1031, 2cf9cbfe39..4408925d25
- finding: installation_from_scope only accepts the exact canonical form; any scope string built elsewhere (e.g. with padding, different prefix casing, or a future scope kind) silently resolves to None, disabling intent without any log or signal.
- addressed: 

## 6. PR#39 `api/tests/test_deviations.py` [reader:brittle-test-on-deploy-file]
- pair 1029->1031, 2cf9cbfe39..4408925d25
- finding: Test parses gcp.sh text and asserts the allowlist equals exactly the dogfood id; legitimately adding a second installation or reformatting the deploy command will fail CI and require a code change.
- addressed: 

## 7. PR#43 `api/doug/migrations.py` [reader:sql-null-semantics]
- pair 1043->1045, 17533f9323..2f2ab6a400
- finding: The partial index and dedupe predicates use `tier <> 'external'`, which evaluates to NULL for rows with NULL tier, silently excluding such rows from both dedupe and uniqueness. If any legacy App-path row has NULL tier, uniqueness is not actually enforced for it (and any mismatch with find_verdict_by_identity's filter would produce inconsistent dedupe behavior).
- addressed: 

## 8. PR#43 `api/doug/store.py` [reader:awkward-out-parameter]
- pair 1043->1045, 17533f9323..2f2ab6a400
- finding: save_review signals insertion via a mutable `created` list out-param; callers must distinguish [] (storage disabled) from [False] (race). Any future caller or early-return path that forgets to mark the list will be silently treated as 'not a race' or vice versa.
- addressed: 

## 9. PR#48 `api/doug/api.py` [reader:auth-scope-bypass]
- pair 1062->1064, 30fdf38616..e8cf8cb2e6
- finding: In /v1/queue the tenant scoping only applies in the `store.enabled()` branch. If storage is disabled/unavailable, the code falls through to the non-store queue path and returns items unfiltered, so a tenant token would see all in-memory/global queue rows (and a cross-tenant `repo` check is also skipped since active_repos would be empty — though that path 404s only when repo is supplied).
- addressed: 

## 10. PR#48 `api/doug/api.py` [reader:unbounded-external-calls]
- pair 1062->1064, 30fdf38616..e8cf8cb2e6
- finding: /v1/installations/token is intentionally unauthenticated apart from a caller-supplied PAT and performs two GitHub API calls per request with no rate limiting or throttling; even with caller-first ordering, a valid-PAT attacker can repeatedly reach the app-JWT call and consume Doug's shared 5,000/hr quota, plus repeatedly rotate/invalidate a tenant's live token.
- addressed: no — carried over: findings-log `real`; only docs/findings-log.jsonl changed in the pair. Confirm.

## 11. PR#48 `api/doug/api.py` [reader:error-handling-gap]
- pair 1062->1064, 30fdf38616..e8cf8cb2e6
- finding: _operator_only now calls tenancy.resolve() on every operator endpoint request, adding a DB round-trip inside auth; a DB outage or missing table turns previously simple 401/200 auth into unhandled 500s on /v1/patterns, /v1/comparisons and /v1/score/read.
- addressed: no — carried over: findings-log `real`, `changed=true`, but api.py untouched in this pair — fixed later. Confirm.

## 12. PR#48 `api/doug/api.py` [reader:validation-gap]
- pair 1062->1064, 30fdf38616..e8cf8cb2e6
- finding: Repo parsing uses partition and rejects '/' in the name but does not reject '/' in owner or extra path segments beyond the first split edge cases (e.g. 'a/b/c' is rejected, but whitespace/URL-encoded values pass through to the GitHub call).
- addressed: 

## 13. PR#48 `api/doug/tenancy.py` [reader:schema-migration-gap]
- pair 1062->1064, 30fdf38616..e8cf8cb2e6
- finding: tenancy.mint/resolve depend on an `installations.token_hash` column, but no migration/DDL change is visible in the diff. If the column is not created/backfilled in existing deployments, mint and resolve will raise operational errors on every request (500s on /v1/queue via _operator_only too).
- addressed: 

## 14. PR#50 `api/deploy/gcp.sh` [reader:config-dependency]
- pair 1074->1076, 8d6f817d7d..0a3e0b7f1a
- finding: Token verification/minting now requires DOUG_TOKEN_PEPPER; environments where the new secret has not been created will return 503 on tenant token paths, and the deploy --set-secrets reference will fail hard if the secret does not yet exist (setup only warns and continues).
- addressed: 

## 15. PR#50 `api/doug/migrations.py` [reader:error-swallowing]
- pair 1072->1073, a0591d6653..fe307ab6ec
- finding: _SATISFIED gains the broad substring "no such column", and _satisfied() swallows any Postgres error containing both "does not exist" and "column". Future migrations referencing a genuinely missing column (e.g. a typo in an ADD/UPDATE statement) will silently succeed, leaving schema drift undetected.
- addressed: 

## 16. PR#56 `api/doug/reader.py` [reader:behavior-change-invalidates-validation]
- pair 1096->1097, d1cb8991f6..b07e176ae8
- finding: Raising DIFF_BUDGET from 30k to 100k and reordering files by tier changes the model's input distribution relative to the frozen probe that produced the AUC evidence; scoring quality/cost/latency may regress in production even though the five prompt constants are unchanged.
- addressed: 

## 17. PR#56 `api/doug/review.py` [reader:ordering-side-effects]
- pair 1096->1097, d1cb8991f6..b07e176ae8
- finding: read_order sorts by (tier, patch length), so the largest code file in a PR is now the most likely to be cut/dropped and GitHub's natural diff order is no longer preserved for the reader; any downstream consumer assuming original file order in the assembled diff (e.g. stored coverage comparisons or prompt heuristics) could behave differently.
- addressed: 

## 18. PR#59 `api/doug/backtest/git_labels.py` [reader:behavior-divergence]
- pair 1107->1108, 81b8a62b18..df1331dec7
- finding: Two attribution rules now coexist (string order for backtest, instant+sha for live). Cached backtest corpora and live labels can disagree on multi-offset repos, weakening the claimed 'same event' invariant the change is meant to establish.
- addressed: 

## 19. PR#69 `api/doug/api.py` [reader:api-contract-change]
- pair 1124->1125, 5db1850df2..f5ae6a7875
- finding: enqueue_outcome_jobs changes the return type from int|None to dict[int,int]; the api.py caller was switched but any other caller or monkeypatched test double expecting the old scalar contract would silently misbehave.
- addressed: 

## 20. PR#69 `api/doug/store.py` [reader:error-handling-gap]
- pair 1124->1125, 5db1850df2..f5ae6a7875
- finding: Dedupe moved from catching IntegrityError with an explicit constraint-name check to blanket ON CONFLICT DO NOTHING on the outcome identity. Real duplicate-key situations that previously surfaced (e.g. a partially conflicting row inserted by another writer, or a conflict on a different unique index) are now silently absorbed for the identity columns, and enqueue_outcome_job now returns None in cases that previously raised, so a merge can drop out of the denominator without a signal.
- addressed: 

## 21. PR#75 `api/deploy/gcp.sh` [reader:deploy-ordering-hazard]
- pair 1144->1145, 93a566b663..70fe216ca6
- finding: web and api deploy in parallel (deploy.yml web job is `needs: changes` only). If web lands first, the public pages call /v1/showcase/queue on an api that doesn't serve it yet and silently fall back to the bundled fixture; promote_if_healthy smokes `/`, which returns 200 either way, so the gate cannot catch it.
- addressed: yes — carried over: adjudicated `fixed` inside the pair by 70fe216 — but the fix landed in deploy.yml, not the cited gcp.sh. THE pre-declared expected false-persisted (Bar B allows <=1/26). Confirm.

## 22. PR#75 `api/deploy/gcp.sh` [reader:missing-smoke-test]
- pair 1144->1145, 93a566b663..70fe216ca6
- finding: No smoke check verifies /v1/showcase/queue after deploy; a missing or wrong DOUG_SHOWCASE_REPO yields a 404 and a silent fixture fallback on the public pages while health checks stay green.
- addressed: no — carried over: fix e681064 lands after to_head; defect still present in the pair. Confirm.

## 23. PR#75 `api/doug/api.py` [reader:unauthenticated-data-exposure]
- pair 1144->1145, 93a566b663..70fe216ca6
- finding: /v1/showcase/queue filters store.latest_reviews on the display-only `repo` string across all installations, on a public unauthenticated surface. If two installations have a repo with the same full name (or the env var is misconfigured), the public page can leak another tenant's PR titles, authors and reader rationales. Authorization elsewhere keys on github_repo_id.
- addressed: no — carried over: findings-log `real`; fixes 7430600+b6253c9 land after to_head. Confirm.

## 24. PR#75 `web/package.json` [reader:tooling-compat]
- pair 1144->1145, 93a566b663..70fe216ca6
- finding: The test script relies on node's --test accepting a quoted recursive glob ('lib/**/*.test.mjs'); on Node versions without glob support in --test this passes a literal path and matches nothing (the pretest guard only checks files exist, not that they ran), reintroducing the vacuous-green problem the change intends to fix.
- addressed: 

## 25. PR#90 `web/lib/coverage.ts` [reader:semantics-change]
- pair 1169->1170, 00798b2967..a1d0d86d61
- finding: Coverage denominator switched from sent_chars/diff_chars to files_sent/changed_files, which also silently redefines the 'coverage < 50%' filter; rows with missing changed_files are now excluded from that filter entirely.
- addressed: 

## 26. PR#90 `web/lib/dashboard-model.ts` [reader:pagination-assumption]
- pair 1169->1170, 00798b2967..a1d0d86d61
- finding: capSuffix compares items.length to limit but the request pins offset=0 and limit=500; if the API ever caps below the requested limit or returns a different limit, the note could misreport, and runs beyond 500 are silently unavailable with no paging.
- addressed: 

