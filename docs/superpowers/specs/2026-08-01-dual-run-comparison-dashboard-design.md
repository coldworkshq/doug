# Dual-Run Comparison Dashboard Design

## Goal

Make the App-versus-CI soak run measurable in the existing web dashboard. A human must be able to see both verdicts for each recent PR head, spot a missing App or CI result, understand whether score gaps came with different tiers or coverage, and judge the direction and size of divergence without taking screenshots.

This is an operational comparison surface for deciding when the CI path can be retired. It is not the M3 public scoreboard and it does not change either review path.

## Scope and constraints

- Add one token-gated read endpoint and one new store read. Do not change `store.latest_reviews` or `/v1/queue`.
- Add a separate `/compare` web route and link it from the existing dashboard navigation. Do not fold soak evidence into the operational queue.
- App rows are rows whose `installation_id`, `github_repo_id`, and `head_sha` are all set. CI rows are rows where all three are `NULL`. Rows with a partial identity are neither path and must not appear.
- Exclude `tier='external'` rows. Third-party reviews are not one side of this experiment.
- Preserve every qualifying verdict row. In particular, do not assume the future migration 003 uniqueness constraint already exists and do not collapse duplicate App verdicts.
- Show `tier` and stored read coverage with every score. A deterministic verdict or a reader verdict without a coverage row must say coverage is unavailable; the UI must not infer a full read.
- Keep the shared-token gate and optional repo filter used by `/v1/queue`. The token prevents anonymous reads but does not provide tenant isolation.
- Do not add WorkOS, authentication, spend controls, migration 003, reader changes, or edits to files owned by the concurrent safety session.
- When the comparison read is unavailable, show an unavailable state. Do not substitute fixture data and present it as soak evidence.

## Alternatives considered

### Separate comparison route — selected

Add `/v1/comparisons` and `/compare`. This keeps temporary cutover evidence separate from the queue's attention-routing job, gives missing-path failures enough visual priority, and keeps the existing queue contract unchanged.

### Extend `/queue`

This avoids another route but combines two different questions: “what needs review?” and “is the App path reliable enough to replace CI?” It would also make every queue row substantially denser. Rejected.

### Aggregate-only comparison

This would show a few means and counts but hide the exact PR, coverage, tier, duplicate, and missing-run evidence needed to explain the numbers. Rejected.

## Store read

Append `comparison_reviews(limit=50, repo=None)` to `api/doug/store.py`.

The query first selects the requested number of most recently scored `(repo, pr_number)` groups among qualifying App and CI rows. It then returns every qualifying verdict for those PRs, ordered by the PR's latest score time and then by verdict time and id. Selecting recent PR groups before joining their runs avoids cutting one side of a pair at a row-limit boundary and keeps all pushes and duplicates for each selected PR.

For every verdict, the function returns the verdict columns plus an optional `coverage` object read from `reads`: `diff_chars`, `sent_chars`, `files_sent`, `files_unseen`, and `file_cut`. The function does not manufacture coverage from tier or findings. Storage disabled returns an empty list, matching other store reads; the endpoint is responsible for distinguishing that condition from a configured empty ledger.

The path predicate is explicit in SQL:

- App: all three identity columns are non-NULL.
- CI: all three identity columns are NULL.
- Mixed identity and external-tier rows: excluded.

The store function remains a lossless ledger read. It does not group runs, select a winner, or calculate deltas.

## API contract

Append `GET /v1/comparisons` to `api/doug/api.py`. It accepts `repo` and a `limit` from 1 through 200, uses the same `X-Doug-Token` checks and error codes as `/v1/queue`, and returns `503` when the ledger is not configured.

The response is:

```json
{
  "runs": [
    {
      "id": 42,
      "repo": "drewjst/doug",
      "pr_number": 33,
      "title": "Example change",
      "url": "https://github.com/drewjst/doug/pull/33",
      "head_sha": "0123456789abcdef",
      "path": "app",
      "scored_at": "2026-08-02T05:12:00Z",
      "score": 0.02,
      "band": "cleared",
      "threshold": 0.3,
      "tier": "reader",
      "coverage": {
        "diff_chars": 12000,
        "sent_chars": 12000,
        "files_sent": 4,
        "files_unseen": [],
        "file_cut": null
      }
    }
  ]
}
```

`path` is derived from the three identity columns, never from score, tier, or display metadata. `head_sha` uses the App identity column when present and the CI row's stored `pr_meta.head_sha` otherwise. A missing CI metadata SHA remains `null`; it is not guessed. `title` and `url` come from `pr_meta`, with the same repository-and-number URL repair used by the queue when an old row lacks a URL.

The response intentionally stays flat. Flat events preserve duplicates and make the backend contract independently inspectable; grouping and presentation statistics belong to the dashboard.

## Web data model and grouping

Append comparison response types, structural validation, and `getComparisons()` to `web/lib/api.ts`. It calls `/v1/comparisons`, applies `DOUG_QUEUE_REPO` as the repo scope, sends the server-only shared token, disables caching, and returns either live data or an explicit unavailable result. There is no comparison fixture.

Add `web/lib/comparison.ts` as a pure transformation from flat runs to revision groups and summary metrics. A revision key is `(repo, pr_number, head_sha)`. A run without a head SHA receives a run-specific unknown key so two unknowns can never be falsely paired.

Each revision group contains all App runs and all CI runs. Its path-presence state is:

- `paired`: at least one App run and at least one CI run.
- `app-only`: one or more App runs and no CI run.
- `ci-only`: one or more CI runs and no App run.

Separately, a group is marked `duplicate` whenever either path has more than one run. This preserves both facts when, for example, two App attempts exist and CI is missing. Duplicates remain rendered as individual attempts. Only a paired, non-duplicate group is an exact pair; a duplicate group does not contribute to score-gap statistics because choosing a run or creating a Cartesian set of deltas would silently invent a pairing.

Only exact pairs contribute to:

- Signed mean gap: mean of `App score - CI score`, showing systematic direction.
- Mean absolute gap: mean of `abs(App score - CI score)`, showing typical distance.
- Maximum absolute gap: the largest observed paired difference.

Every metric carries the paired head count. These are descriptive soak statistics, not a significance test; the page must not label a small observed mean as “noise” or claim equivalence.

## Dashboard presentation

Add `web/app/compare/page.tsx`, following the existing dark glass-and-iridescence visual system.

The page contains:

1. A live/unavailable source badge and a short explanation that this compares two reads of the same head during cutover.
2. Summary cards for paired heads, missing App, missing CI, duplicate groups, signed mean gap, and mean absolute gap. Missing App is the highest-alert treatment because it is the silent failure mode.
3. A revision list ordered by most recent run. Each card shows repository, PR, short SHA, status, and the signed gap when the group is an exact pair.
4. Side-by-side App and CI columns. Every run displays score, tier, timestamp, and coverage as both a percentage and sent/total characters. Partial coverage names the cut file and unseen files when recorded. Missing coverage is labeled rather than interpreted.
5. Explicit empty and unavailable states.

The landing and queue navigation gain a `Compare` link. The comparison route links back to the queue and repository.

The UI may visually connect the two singleton scores on a zero-to-one scale, but the exact numbers, tier, and coverage remain primary. Color alone never carries missing or duplicate status.

## Error handling

- Missing or incorrect API token: preserve `/v1/queue`'s `503` and `401` behavior.
- Ledger not configured: API returns `503`; web renders unavailable.
- Configured ledger with no qualifying rows: API returns `{"runs": []}`; web renders an honest empty state.
- Malformed API response, timeout, or network failure: web renders unavailable and never falls back to queue fixtures.
- Missing `pr_meta`: retain the run with fallback title `PR #<number>`, repaired GitHub URL, and only identity-backed fields. Do not drop a missing-path signal because display metadata is incomplete.
- Missing head SHA: keep the run visible but unpaired.
- Missing coverage row: show “coverage unavailable.”

## Verification

API store tests will prove:

- App and CI predicates include both paths while excluding mixed-identity and external rows.
- Duplicate App rows remain separate.
- Repo scope and recent-PR limit do not cut a selected PR's other runs.
- Coverage is attached to the correct verdict and remains `None` when absent.
- Disabled storage returns an empty store result.

API endpoint tests will prove:

- Shared-token configuration, rejection, and success match `/v1/queue`.
- An unconfigured ledger returns `503`.
- Path classification, CI metadata SHA, App identity SHA, fallback metadata, coverage, and duplicate rows survive serialization.

Web tests will use Node's built-in test runner with TypeScript stripping, adding no package dependency. They will prove:

- Structural response validation rejects fields the page dereferences when malformed.
- Exact pairs produce the expected signed, absolute, and maximum gaps.
- Missing App and missing CI counts are separate.
- Duplicates remain visible and do not enter aggregate deltas.
- Missing SHAs cannot pair accidentally.

Mutation checks will deliberately break the identity predicate, duplicate preservation, coverage attachment, and web pairing rule; each named test must fail before the code is restored.

Every commit must pass:

```bash
cd api && uv run pytest -q
cd api && uv run ruff check .
cd web && npm test
cd web && npm run lint
cd web && npm run build
```

No deployment or merge is part of this task. Completion is a pushed branch and an open pull request.
