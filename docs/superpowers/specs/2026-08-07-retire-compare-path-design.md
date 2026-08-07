# Retire `/compare` and the dual-run comparison stack

**Status:** design approved (Andrew, 2026-08-07) · **Milestone:** none —
cleanup after CI-path retirement
**Closes:** HANDOFF note that `/compare` gets deleted with PR #54 Task 9
**Depends on:** PR #54 merged (`e1aea0f` — CI-token review path retired)

The dual-run comparison dashboard existed to measure App vs CI soak instruments
during cutover. Task 9 deleted the CI path; the comparison surface is now
meaningless and still linked from production `doug-web`. Remove the live stack
and scrub operational docs so nothing still presents it as current.

---

## Scope

### Delete (live surface)

| Layer | Paths |
|---|---|
| Web route | `web/app/compare/page.tsx` |
| Nav links | Compare links in `web/app/page.tsx` and `web/app/queue/page.tsx` |
| Web client | `web/lib/comparison.ts`, `web/lib/comparison.test.mjs`; `getComparisons()` and comparison type re-exports from `web/lib/api.ts` |
| API | `GET /v1/comparisons`, `_comparison_run`, `_comparison_path` in `api/doug/api.py` |
| Store | `comparison_reviews()`, `COMPARISON_RUN_LIMIT`, `ComparisonResultTooLarge` in `api/doug/store.py` |
| Tests | Comparison-only cases and helpers in `api/tests/test_api.py` and `api/tests/test_store.py`; drop `/v1/comparisons` from operator-auth parametrize lists |

### Update (operational docs)

- `docs/REVIEWING.md` — paragraphs that present `/compare`, `_comparison_run`,
  or comparison 413/unavailable behavior as a **live** soak instrument.
  Keep transferable review lessons (trace errors through consumers, do not
  invent fallbacks for impossible row shapes, etc.) but strip present-tense
  claims that the comparison surface still exists. Sections whose only
  subject is the deleted instrument may be removed entirely.
- `HANDOFF.md` (workspace root and `repo/HANDOFF.md` if both still carry the
  note) — change “`/compare` gets DELETED” from future work to done, or
  remove the dangling instruction.
- `docs/design/outcome-loop/ROADMAP.md` — only if a present-tense claim still
  treats `/v1/comparisons` as a live soak dependency; historical tense about
  mid-soak rationale may stay.

### Leave as history (banner only)

- `docs/superpowers/specs/2026-08-01-dual-run-comparison-dashboard-design.md`
- `docs/superpowers/plans/2026-08-01-dual-run-comparison-dashboard.md`

Add a one-line retired banner at the top of each (retired after PR #54 /
CI-path retirement). Do not rewrite the bodies.

Tenant-token design/plan docs that list `/v1/comparisons` as an operator-only
endpoint example stay untouched — they are historical build records.

---

## Non-goals

- No ledger or schema migration; historical App/CI verdict rows remain.
- No changes to `/queue`, worker, webhook, scoring, App-path review, or
  check-run publishing.
- No Cloud Run / IAM redesign; ordinary web/api deploys pick up the deletion.
- Not stacked on `read-budget-routing`; branch from `origin/main` (which
  already contains PR #54).

---

## Deletion order

Leaf → root so intermediate states do not strand callers:

1. Web UI — delete compare page; remove nav links.
2. Web client — delete comparison module + tests; strip from `api.ts` without
   touching the queue fetch path.
3. API — remove endpoint and helpers; delete comparison API tests; shrink
   parametrize lists to remaining operator paths.
4. Store — remove `comparison_reviews` and related constants/errors + store
   tests (including helpers used only by those tests).
5. Docs — operational scrub + dual-run retired banners.

---

## Verification

- API: full `uv run pytest` green after deletions.
- Web: comparison unit tests gone; run the web package’s existing check
  (`package.json` scripts: lint and/or test and/or build — whichever the
  repo already uses for doug-web); `/` and `/queue` render without a Compare
  link.
- Contract smoke: `/v1/queue` still auth-gated and functional;
  `/v1/comparisons` → 404; `/compare` → Next 404.
- Non-impact: diff contains no edits to worker, webhook, scoring, queue
  serialization, or migrations.

---

## Doc scrub policy (Approach 1)

Operational docs that operators still read get corrected. Historical
superpowers specs/plans get a superseded banner only. No mass rewrite of every
grep hit; no deletion of the dual-run design/plan files.
