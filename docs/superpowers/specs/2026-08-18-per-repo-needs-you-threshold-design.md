# Per-repo "needs you" threshold

**Date:** 2026-08-18
**Status:** design approved in chat 2026-08-18 (D1–D3 locked); revised the same day after a three-lens adversarial review (correctness of code claims, tenancy/authz, product/honesty) — D4–D6 added from it; awaiting Andrew's read, then an implementation plan
**Branch:** `claude/per-repo-needs-you-threshold-f075db`

---

## 1. The gap

Doug decides "needs you" by comparing a 0–1 score to a line. That line is
**process-wide** today, and nothing a tenant can reach moves it:

- `DOUG_THRESHOLD` (default `0.62`) — the deterministic scorer,
  `api/doug/scoring.py:21` (`default_threshold()`), compared at
  `scoring.py:146` with `>=`.
- `DOUG_READER_THRESHOLD` (default `30`, in 0–100 risk points) — the LLM
  reader, `api/doug/reader.py:347` (`reader_threshold()`), compared at
  `reader.py:957` with `>=` against an **integer** `risk_score`
  (`reader.py:338`), and normalised to 0–1 when stamped on the verdict
  (`reader.py:971`, `threshold=thr / 100`).

**Production runs the reader** (`api/deploy/gcp.sh:674`, `DOUG_READER=1`),
so the line most verdicts are actually scored against today is **0.30**;
0.62 applies only when the reader is disabled, capped, or unavailable and
the deterministic scorer runs as fallback. The dashboard has already been
burned once by conflating the two (`api.py:501`, "reporting 0.62 while
showing rows flagged at 0.30"; `_banding_threshold` at `api.py:286` exists
to avoid it). This spec must not repeat that.

Both `score()` (`scoring.py:138`) and `verdict_from_reader()`
(`reader.py:955`) already accept an optional `threshold` argument. **No
production caller passes one.** `review.score_one()` (`review.py:303`) — the
single scoring seam the worker uses (`worker.py:250`, its only production
caller) — has no `threshold` parameter at all, so its four exits (`reader`
at `:366`, `reader-capped` `:381`, `reader-unavailable` `:385`,
reader-disabled `:390`) all fall through to the env defaults.

The resolved line is stamped on every verdict (`store.py:75`,
`verdicts.threshold NOT NULL`) and printed in the check run
(`check_run.py:143`, "Risk 0.71 against a flag line of 0.30"). Two
preview-only surfaces exist: the dashboard's threshold **lens**
(`web/lib/threshold-lens.ts`) re-bands recorded scores against a
reader-chosen line as a *view*, and `/v1/queue?threshold=` (`api.py:508`)
does the same on read. The lens header argues the line "is not a setting
because it cannot be." That describes the current wiring, not a constraint;
this spec reverses it deliberately.

A docs-only repo and a Terraform repo have very different costs for a false
"needs you", and today they share one line.

## 2. Decisions (locked)

- **D1 — Forward-only.** The setting changes verdicts scored *after* it is
  set. Existing verdicts keep the threshold they were scored against; the
  ledger stays a record of what Doug did and posted. The lens remains the
  way to preview a different line over history. Open PRs keep their check
  until a new commit (no re-scoring on change). Rejected: retroactive
  re-banding (the ledger would stop matching the check runs on GitHub).
- **D2 — Dashboard setting, stored per repo.** A nullable column on
  `installation_repos`, written through a session-authenticated API
  endpoint, edited on the dashboard's Repositories view. Rejected: an
  in-repo config file (`.doug.yml`) — a file fetch per review, and the
  dashboard could display but not edit it; and "both" — two sources of
  truth. A repo-file source can be layered later without changing the
  column or the resolution seam. Consequence to say plainly: the row is
  keyed by GitHub's `installation_id`; uninstall + reinstall yields a *new*
  installation and the setting does not carry across, while remove +
  re-add of a repo under the same installation keeps it (§3.1).
- **D3 — One 0–1 number, applied to both scorers.** Verdicts already
  normalise to 0–1 and the lens shares that range. The reader receives
  `round(value * 100)`. Rejected: separate deterministic/reader settings
  (two knobs for one question). **Cost accepted and surfaced, not hidden:**
  because the two defaults differ (0.30 / 0.62), a tenant who sets `0.50`
  *loosens* the reader and *tightens* the fallback in one gesture. The UI
  says so (§3.4) and never prints a single "default" number (D4).
- **D4 — The unset state is shown as two numbers, never one.** "default ·
  0.30 deep read / 0.62 fallback". The connections response carries both
  process defaults. Rejected: printing the deterministic default alone
  (false in production, and the exact lie `_banding_threshold` was built to
  end).
- **D5 — Write authority = organization membership + live repo
  entitlement.** Any signed-in member of the bound WorkOS org whose live
  entitlement (`GET /user/installations/{id}/repositories`) reaches the
  repo may set its line. This is **weaker** than key minting (repo admin,
  `tenancy.py:227/294`) and bind (installer, `api.py:1607`), and is
  accepted because WorkOS org membership is operator-curated (today granted
  only at bind, `workos_client.py:216`) and the setting is reversible and
  fully audited by the verdicts it produces. Named so it can be revisited
  if org membership widens (dashboard invites / domain JIT). Rejected:
  installer-only via `_prove_installer` (a WorkOS read per PATCH, and it
  locks policy to one person).
- **D6 — Deploy in two PRs, web tolerance first.** See §3.6.

**Non-goal, named so it isn't smuggled in:** per-repo *scope* rules ("for
docs repos only look at structure/config files, not content"). That
changes what Doug looks at, not where the line sits. A 0.9 line on a docs
repo means "flag only when the score is very high" (the deterministic
scorer caps at 0.99; most rules weigh 0.20–0.35), which is close to "flag
nothing" on the fallback scorer — the tenant should see that plainly (§3.4).

## 3. Design

### 3.1 Storage

`installation_repos.needs_you_threshold FLOAT NULL` — both homes per
`migrations.py`'s module docstring: the `Table` definition at `store.py:221`
**and** a migration:

```
ALTER TABLE installation_repos ADD COLUMN needs_you_threshold FLOAT
```

Migration version is **the next free one at implementation time** — the
MT3 spec (`2026-08-17-reconcile-sweep-scheduling-design.md` §4.5) has
already claimed 11; whichever lands second renumbers. The drift test checks
presence/agreement, not collisions, so this is a plan-time check.

`NULL` means "inherit the process defaults" — the state every existing row
is in and the state a new row is created in. No per-tenant or
per-installation tier. `store.set_installation_repos()` (the only writer of
this table; callers `api.py:2184/2194/2215`) never DELETEs
(`store.py:1059`); `replace=True` flips absent rows to `state='removed'`
by UPDATE, and its update touches only `full_name/state/updated_at`
(`:1088–1099`). The column therefore already survives a webhook
`removed → added` cycle. A test still pins that (webhooks must not erase
tenant configuration), and the consequence is named: re-adding a repo
under the same installation resurrects its old line.

Range is `0 ≤ x ≤ 1`, endpoints included, matching `threshold-lens.ts`
(`MIN_LENS`/`MAX_LENS`) and its reasoning: 0 ("flag everything") and 1
("flag nothing this scorer reaches" — `score()` caps at 0.99) are both
legitimate. Validated at the write endpoint (§3.3), never coerced. Storage
rounds to two decimals to match `Verdict.score` (`scoring.py:147`) and to
make the reader conversion an exact integer (§3.2).

### 3.2 Resolution and the scoring seam

Two store functions, both keyed on the unique constraint
`(installation_id, github_repo_id)` (`store.py:231`) — never on
`github_repo_id` alone, because a transferred repo legitimately has rows
under two installations (`repo_id_for` docstring, `store.py:3312`):

```python
def repo_threshold(installation_id: int, github_repo_id: int) -> float | None:
    """The repo's own needs-you line, or None to inherit the defaults."""

def set_repo_threshold(installation_id: int, github_repo_id: int,
                       value: float | None) -> bool:
    """Write the line on the ACTIVE row; False if no such row (→ 404)."""
```

`repo_threshold` reads regardless of `state`: it is only ever called with
the job's own `installation_id`, and a repo removed mid-job still scores
against the line it had. `set_repo_threshold` writes **only that column** —
it does not bump `updated_at`, because `repo_id_for` (`store.py:3344`)
orders competing same-`full_name` rows by `updated_at.desc()` and a
settings PATCH must not be a lever over that tie-break. Its WHERE includes
`state = 'active'`, closing the gap between the scope check and the write.

`review.score_one()` gains `threshold: float | None = None` and threads it
to **every** exit:

- `reader.verdict_from_reader(rv, threshold=None if t is None else round(t * 100))`
  — `round`, not bare `* 100`: `0.55 * 100 == 55.00000000000001`, and with
  an integer `risk_score` compared by `>=` a PR sitting exactly on the line
  would clear at 0.07/0.14/0.28/0.55/0.56 while the check run printed
  "Risk 0.55 against a flag line of 0.55". Storage rounding to 2dp makes
  the product an exact integer by construction.
- `score(meta, threshold=t)` on `reader-capped`, `reader-unavailable`, and
  the reader-disabled path.

The fallbacks matter as much as the happy path: a capped read on a 0.9 repo
must not band at 0.62 because the fallback forgot the argument. Both
functions keep `None → env default`, so every other caller (`review.py:463`
`review_repo`, the CLI/dogfood path with `SENTINEL_SCOPE`; `api.py:245`;
tests) is unchanged.

`worker.py:250` becomes:

```python
threshold = store.repo_threshold(job["installation_id"], job["github_repo_id"])
tier, verdict, rv, cov = review.score_one(
    meta, diff, scope=scope, threshold=threshold,
    resolve_file=resolve, resolve_schema=store.columns_of,
)
```

Read **inside the job, at scoring time** — not at admission — so the line
in effect when Doug scores is the one stamped. `Verdict.threshold` is
stamped as today, so the ledger row records the line the repo had, the
check run prints it, `_replay_recorded` (`worker.py:97`) replays the peer's
stamped line, and `web/lib/ledger-census.ts` already renders rows with
differing lines honestly ("thresholds differ — no single line to draw").

**Observability (two log lines, no schema):** the worker's success line
(`worker.py:327`) gains `line={verdict.threshold:.2f}
line_source={repo|default}` — a stamped 0.62 is otherwise indistinguishable
between "repo set to 0.62" and "fallback default" once the tenant clears
the setting. The PATCH logs `doug: needs_you_threshold installation={id}
repo={id} {old}->{new} by sub={workos_user_id}` to stderr, matching the
convention at `api.py:1733/2012`.

**A false claim removed:** the queue's mode-of-thresholds heuristic
(`_banding_threshold`, `api.py:286`) does *not* "keep working" — it was
built for a tier split, and once one installation has repos at 0.30 and
0.90, `/v1/queue`'s `summary.threshold` reports the mode while the other
repo's rows are banded at their own line; `web/app/queue/page.tsx:46` seeds
presets from it. `/v1/queue?repo=` is exact. Making `summary.threshold`
nullable when mixed is deferred (§3.5) — the census already handles the
mixed case, and the queue page is the only consumer.

`tests/test_worker.py:144` and `:1012` monkeypatch `score_one` with fixed
signatures and will need `threshold=` — plan item.

### 3.3 API

**Write.** `PATCH /v1/sessions/repositories/{github_repo_id}` — body
`{"needs_you_threshold": <number 0..1> | null}`.

- **Auth:** a new session scope `settings:write` added to
  `SESSION_SCOPES` (`session_auth.py:27`, today `queue:read`,
  `receipt:read` only), resolved through `session_auth.resolve_session()`
  via a `_session_write_context` sibling of `_session_read_context`
  (`api.py:1181`). Tenant API keys (`mint_key`, `tenancy.py:389`) never
  carry it, and the endpoint must **not** use the dual read-context
  resolution shape at `api.py:559`. `resolve_session` fails closed without
  `org_id`, on unknown org, on missing/stale entitlement, on non-active
  installation, on empty live intersection (`session_auth.py:178–195`) —
  so `setup_required` and `reauthorize_required` sessions cannot write.
- **Tenancy:** `installation_id` comes from `ctx.installation_id`
  (`installations.workos_org_id` is UNIQUE, so one org → one installation),
  never from the body or path. `github_repo_id` must be in the session's
  live scope; then `store.set_repo_threshold(ctx.installation_id,
  github_repo_id, value)`; rowcount 0 → `404`. Out-of-scope is `404`, not
  `403` — do not confirm the repo exists.
- **Body model:** `needs_you_threshold: float | None = Field(...,
  strict=True, allow_inf_nan=False, ge=0, le=1)` — required, so `{}` is
  `422` rather than a silent clear; `strict` rejects `"0.9"`, `"62"` and
  `true`; `NaN`/`Infinity` rejected; ints 0/1 accepted; `null` clears.
- **Response:** `200 {"needs_you_threshold": <stored value | null>}` — the
  stored value, so a `0.6249` request visibly becomes `0.62`.
- No rate limiting (none exists anywhere in the API; this call is one
  JWKS-cached verify + a few SELECTs + one UPDATE, cheaper than
  `/v1/sessions/entitlements` which spends GitHub calls). Last-writer-wins
  between two members; no `If-Match`. Stated, not solved.

**Read.** `GET /v1/sessions/connections` (`api.py:1877`) adds
`needs_you_threshold: number | null` to each entry of `repositories[]`
(built in `store.session_connections_for`, `store.py:3189`, already
intersected with the user's claimed repo ids, so a value is visible only to
someone GitHub says reaches the repo), and top-level
`default_needs_you_threshold: {"reader": 0.30, "fallback": 0.62}` — both
process defaults, per D4. Nothing here leaks across tenants: `/v1/queue`
already exposes per-verdict `threshold` to key holders within scope.

### 3.4 Web

`web/lib/session-api.ts`: `RepositoryConnection.repositories[]` gains
`needs_you_threshold: number | null`; `ConnectionsResponse` gains
`default_needs_you_threshold: {reader: number; fallback: number}`; a
`setRepositoryThreshold(accessToken, githubRepoId, value)` client for the
PATCH that sends a JSON number or `null`, never a string. **The response
guards** `repository()` (`session-api.ts:192`) and `isConnectionsResponse()`
(`:221`) use `exact()` key matching and will *throw* on the new keys —
see §3.6 for why that dictates deploy order.

**Naming, required in code, not asserted:** the toolbar's `ThresholdGear`
(`page.tsx:1462`, rendered on both views, button text "needs-you line" at
`threshold-gear.tsx:52`) sits a few pixels above the per-row setting on
the Repositories view and *changes the counts beside it*. Two controls
both called "needs-you line" would be the confusion the spec must design
out. Gear button text becomes **"preview at…"** (its popover header
already says "Show needs-you at"); the per-row setting is the **"flag
line"** — the words the check run uses. A web contract test asserts the two
strings differ.

Repositories view (`web/app/dashboard/page.tsx`, repositories table around
`:833`), for rows in `door.current` (which is `ready` by construction and
matches the session's `org_id`, so the PATCH can only ever reach the
selected org's repos; "not connected" rows at `page.tsx:899` have no
`installation_repos` row and get neither value nor control):

- Column **"flag line"**: unset → "default · 0.30 deep read / 0.62
  fallback"; set → "0.90". Edit affordance opens an inline control: numeric
  input, `0`–`1`, `step 0.01` (the units the check run and lens speak; the
  deterministic scorer has only ~33 distinct scores so many stops are dead
  on it, but the reader is integer-valued so every stop is live — a
  slider with two reference marks at 0.30 and 0.62 is honest without
  importing rule weights into web), a "Reset to default" action, and a
  Save. Server action in `web/app/dashboard/actions.ts` following
  `finishSetupAction`'s pattern (`:23–27`: parse the id from FormData,
  `getConnections` → `frontDoor(connections, auth.organizationId)` →
  require the id in `door.current.repositories` → PATCH with
  `auth.accessToken`; a `401` maps to "sign in again"). `revalidatePath`
  after. `dashboard-contract` assertions: `^"use server"`,
  `action={setThresholdAction}`, no `export async function GET`.
- Copy in the control, verbatim intent: **"One line for both scorers.
  Unset, Doug uses 0.30 on deep reads and 0.62 when the reader didn't
  run. Applies to reviews from now on — past verdicts keep the line they
  were scored against, and open PRs keep their check until a new
  commit."** At `≥ 0.90`, one more sentence: "Close to flag-nothing on the
  fallback scorer." Below the control: "This is Doug's line for new
  reviews — the preview gear above only re-bands what's on screen."

**Check run copy** (`check_run.py:143`): provenance is not in `Verdict`, so
a static clause that is always true after this ships is appended to the
risk line — **"The flag line is set per repository on the Doug
dashboard."** Byte-locked check-run tests update accordingly.

The `threshold-lens.ts` header is rewritten: the lens is a **preview** over
recorded scores (`/v1/queue?threshold=` is the API's equivalent); the
**setting** is per-repo, forward-only, and lives on `installation_repos`.
Both stay, with distinct jobs, and each names the other. Same reversal
recorded as `docs/decisions/ADR-0013-needs-you-line-is-a-per-repo-setting.md`
in the README's format — context, decision (D1–D6), consequences,
**Rejected** (retroactive re-band, `.doug.yml`, two knobs, single-default
display, installer-only writes) — status `accepted` on merge, since
accepted ADRs are fed to the reader.

Console (`console/`) is untouched: the five byte-locked readers
(`buildFacets`, `matchesFacets`, `groupRunsByPr`, `BandChip`,
`runMatchesQuery`) still read `run.band` and nothing changes what `band`
means on a row.

### 3.5 Out of scope (named)

- Lens auto-defaulting to the repo's setting when the ledger is filtered
  to one repo.
- Per-installation / per-org default tiers.
- Re-scoring open PRs when the setting changes (copy tells the tenant).
- Per-repo scope/path rules (§2 non-goal).
- Exposing the setting on the tenant API-key surface.
- `QueueSummary.threshold` nullable when an installation's repos differ
  (`/queue` page presets are the only consumer; `?repo=` is exact today).
- A "since <first verdict at this line>" annotation on the row (needs a
  per-repo ledger query; the census already renders mixed lines honestly).
- A `threshold_source` column (the log line covers the operator question).

### 3.6 Deploy order (D6)

`.github/workflows/deploy.yml:162` promotes API before web (`web: needs:
[changes, api]`). The current web guards throw on unknown keys, so an API
that starts emitting `needs_you_threshold` / `default_needs_you_threshold`
breaks every signed-in dashboard load until web catches up —
`getConnections()` is called by the dashboard page and
`switchConnectionAction`. Therefore:

- **PR 1 (web only):** `repository()` and `isConnectionsResponse()` accept
  the two new keys as *optional* (still `exact` on everything else). Ships
  and deploys alone.
- **PR 2:** everything else in this spec, including the web UI that
  *requires* the fields.

The migration itself is safe in either order: nullable column, `apply()`
after `create_all()`, old code ignores it, new code treats absent as
`None` (ADR-0011).

## 4. Failure modes considered

- **Web guard rejects the new fields during deploy.** §3.6, two PRs.
- **Single "default" number lies.** D4; both defaults surfaced.
- **Setting one number moves the two scorers in opposite directions.**
  D3 cost, stated in the control's copy.
- **Exact-line PR mis-banded by float `×100`.** `round()`; test at
  0.55/55 (0.5/50 cannot fail).
- **Setting reset by webhook re-sync.** Verified not to happen; test pins
  it; resurrect-on-re-add named.
- **Fallback path forgets the line.** Threaded to all four exits; worker
  test exercises `reader-unavailable`.
- **Cross-tenant write.** `installation_id` from session context; write
  keyed on `(installation_id, github_repo_id, state='active')`; `404`
  otherwise; test with one `github_repo_id` under two installations.
- **Read-only collaborator moves the line.** D5 accepts and names it.
- **PATCH as a tie-break lever.** `updated_at` not touched.
- **`{}` clears the setting / `true` coerces to 1.0.** Required strict
  field.
- **Two same-named controls on one view.** "preview at…" vs "flag line",
  contract test.
- **Operator can't tell repo line from default in logs.** `line_source`.
- **Migration number collision with MT3.** Next free at plan time.

## 5. Tests that encode intent

- `worker` / `review`: a PR whose deterministic score is `0.71` bands
  `flagged` on an unset repo and `cleared` on a repo set to `0.9`, and the
  same on the `reader-unavailable` fallback — *the setting must reach the
  scoring seam and survive fallback, or the tenant's line is fiction on
  exactly the reviews they can't see happening.*
- `reader.verdict_from_reader`: a repo line of `0.55` bands `risk_score
  55` `flagged` and `54` `cleared`, and stamps `threshold == 0.55` — *on
  the line means needs you, on both scorers, with no float leak.*
- `store`: `set_installation_repos(replace=True)` then re-add leaves the
  line in place; `repo_threshold` is `None` for unset and unknown;
  `set_repo_threshold` with the same `github_repo_id` under two
  installations touches only the caller's row and returns `False` for a
  removed row; `updated_at` unchanged by a write — *webhooks must not erase
  tenant configuration; one tenant's PATCH must not reach another's row or
  the operator's tie-break.*
- `api`: PATCH `422` on `1.5`, `-0.1`, `"0.9"`, `"62"`, `true`, `NaN`,
  `{}`; `200` with the stored value on `0.9` and `null`; `404` for a repo
  outside the session's live scope; `401` for a `queue:read`-only context
  and for a tenant API key; connections response carries per-repo values
  and both defaults; PATCH emits the audit line — *fail closed, don't
  guess, don't leak, leave a trail.*
- `check_run`: byte-locked output includes the per-repo clause.
- `migrations`: new version present, two-homes agreement.
- `web/lib/session-api.test.mjs`: PR 1 — guards accept responses with and
  without the new keys; PR 2 — `setRepositoryThreshold` sends a JSON
  number or `null`, never a string; contract test that the gear's label
  and the row setting's label differ; `dashboard-contract` assertions for
  the new server action.
