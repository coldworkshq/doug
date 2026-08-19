# MT3 — reconcile sweeps must not scale by repo count

**Date:** 2026-08-17
**Status:** design approved 2026-08-17 — all decisions locked (D1–D5), ready for an implementation plan
**Roadmap item:** MT3 (`docs/design/outcome-loop/ROADMAP.md:399`), scope amended — see §2
**Blocks:** M5's first outside install

---

## 1. The defect

Four facts, each verified in code rather than taken from the roadmap.

**1.1 Both sweeps are serial across installations, uncapped across repos.**

`reconcile_all` (`worker.py:656`) and `reconcile_all_outcomes` (`worker.py:912`)
both loop `for installation_id in store.active_installations()`. Inside,
`reconcile_installation` (`worker.py:547`) and `reconcile_outcomes`
(`worker.py:780`) both loop `for repo_id, full_name in
store.active_repos(installation_id)` with **no cap on repo count**.
`_MAX_OPEN_PRS_PER_REPO = 1000` (`worker.py:493`) bounds PRs *within* a repo,
never the number of repos.

Cost per repo is up to 10 paginated calls (`per_page=100`, cap 1000). A
10k-repo installation is therefore ≥10k REST calls per sweep, serially, and one
large tenant delays every tenant behind it.

**1.2 The review lane has no Job — only a daemon thread that gets reaped.**

`reconcile_all_outcomes` has two callers: the API startup thread (`api.py:145`)
and the `doug-outcome-reconciler` Cloud Run Job on a 6h schedule
(`reconcile_worker.py:46`, deployed via `deploy/gcp.sh:50-51`).

`reconcile_all` has **exactly one** caller: `api.py:142`, inside a
`threading.Thread(daemon=True)` started at `api.py:188`. The thread is daemon
by deliberate design — blocking the lifespan fails Cloud Run's health check
(`api.py:182-187`).

On scale-to-zero, the container is reaped when idle. A daemon thread gets no
chance to finish.

**1.3 There is no cursor, so the reaped tail is never swept.**

`store.active_repos` (`store.py:3257`) has **no `ORDER BY`**. Every sweep
restarts from whatever order Postgres returns — in practice heap order, stable
until the rows are updated. Combined with 1.2: on a large installation the
sweep is killed partway through, and the next cold start begins again at the
same place and is killed at the same place.

**This is the finding that reframes MT3.** The repos past the reaping point are
never reconciled on any cold start, ever. It is not slowness — it is a
permanent, silent coverage hole. The roadmap files MT3 as a scaling item; it is
a correctness item.

**1.4 Both lanes draw on one shared per-installation rate limit.**

`api.py:89` already records this: *"the installation token's rate limit is
shared with the review lane"*, which is why the outcome sweep is ordered
deliberately **after** `drain` — *"ahead of drain, an outcome sweep large enough
to exhaust it would starve the paid, user-visible reviews"* (`api.py:90-93`).

Any budget this design introduces must respect that both lanes spend from the
same per-installation pool, and must not silently invert that ordering.

---

## 2. Scope, and two corrections to the roadmap

**Scope amended: both lanes.** MT3's text names only `reconcile_all`. The
outcome lane has the identical uncapped `active_repos` loop and is the more
expensive of the two — `api.py:88` records that it pays *"a pulls.get per merge
in the window, per repo, per installation"*, on every run, even for merges the
ledger already holds. Fixing one lane and leaving the other reopens MT3 the
first time a real org install lands. The scheduling primitive is built once and
applied to both.

**Correction — migration 9 is taken.** MT3's note reads *"Next free migration:
**9** — migration 8 is consumed by M3's receipts slice."* That is stale.
`migrations.py` now carries entries through **10**: 9 is Front Door Phase 1a
(`workos_org_id`, `installed_by_github_user_id`) and 10 is `review_jobs.base_sha`.

**The next free migration is 13** (11 is taken by the per-repo needs-you
threshold, `2026-08-18-per-repo-needs-you-threshold-design.md`, and 12 by the
sticky PR comment,
`docs/decisions/ADR-0014-one-sticky-pr-comment-mirrors-the-check-run.md`;
this section's own earlier "next free is 12" was overtaken by that branch).
**MT3 is unstarted, so its schema below moves with this number.** The ROADMAP
line must be corrected in the
same change, or the next person to read it collides. (Corrected in this change,
at `ROADMAP.md:404` and `:310`.)

**Correction — the roadmap's sketched schema does not close the defect.**
`ROADMAP.md:310` reserved *"MT3's `installations.reconciled_at`"* — a
per-installation timestamp. That cannot work: a single timestamp per
installation records *that* a sweep ran, never *which repos it reached*, and
§1.3's defect is precisely that the sweep reaches a prefix and is killed. Sweep
state has to be per repo. See §4.5.

---

## 3. Decisions locked

| # | Decision | Rejected |
|---|---|---|
| D1 | Design for the org-install case (10k repos), not design-partner scale | Bounding to 2–3 tenants and revisiting at M5 |
| D2 | The full sweep moves to its own scheduled Cloud Run Job, mirroring `doug-outcome-reconciler` | Keeping it in-process with cursor + budget; merging both lanes into one Job |
| D3 | The Job **enqueues only**. `drain` stays in the API on its existing webhook + cold-start triggers | Job POSTs an internal drain endpoint; Job drains in-process |
| D4 | One shared scheduling primitive, applied to both lanes | Review lane only, as MT3 literally reads |
| D5 | The startup thread keeps a **bounded** stalest-N pass (§5) | Accepting the healing-latency regression; shortening the Job cadence |

D3 keeps the Job's service account narrow: no model credentials, no spend-cap
surface, no paid reads on a second deploy path. It matches the outcome lane's
existing split, where `doug-outcome-reconciler` enqueues and the adjudicator
Job drains.

---

## 4. Design: staleness within a tenant, round-robin across tenants

### 4.1 Why not global staleness ordering

The first candidate was a single global query — `ORDER BY last_swept_at NULLS
FIRST LIMIT <budget>` across all installations — on the argument that one
ordering buys coverage, budget, and fairness together.

**It does not buy fairness, and an adversarial pass killed it.** At steady
state every repo converges to the same sweep age, so with budget `B` over `N`
total repos each repo is swept every `N/B` runs. A 10k-repo tenant joining
takes `N` from 50 to 10,050 and degrades every existing tenant's sweep interval
**200×**. That is still "one large tenant delays every tenant behind it" — MT3's
exact words — merely spread evenly rather than blocking serially. A global
budget also lands in the wrong unit given §1.4: it can be consumed entirely by
one already-rate-limited tenant while others sit with headroom.

*A claim made against global ordering and since refuted, recorded so it is not
re-litigated:* it was argued that interleaving repos across installations would
re-mint an installation token per repo, doubling REST cost, because
`app_auth.installation_client` (`app_auth.py:52`) constructs a fresh
`AppInstallationAuthStrategy` per call while both existing loops hoist it
outside the repo loop. **This is false.** githubkit's `DEFAULT_CACHE_STRATEGY`
is a module-level singleton (`githubkit/cache/__init__.py:11`) shared by every
client in the process, and the installation token is cached under a key derived
from `installation_id` (`githubkit/auth/app.py:163`). Verified empirically: two
independently constructed `GitHub` clients return `True` for
`a.config.cache_strategy.get_cache_storage() is b.config...`. Interleaving
costs connection-pool churn, not API calls. Global ordering is rejected on
fairness alone.

### 4.2 The primitive

Each run:

1. List active installations.
2. **Round-robin across them.** For each installation, select its **stalest**
   repos — `ORDER BY last_swept_at NULLS FIRST` — up to a per-installation
   slice.
3. Execute per installation with the client hoisted, exactly as today.
4. **Stamp each repo as it completes**, not batched at the end.
5. Stop when the run's deadline or budget is reached.

What each property comes from:

- **Coverage** — staleness ordering. The least-recently-swept repo always wins,
  so no repo can be starved and the §1.3 tail is structurally impossible.
  Because staleness is derived state rather than a position, repos added or
  removed mid-cycle need no special handling — which is what makes a cursor
  table unnecessary.
- **Fairness** — the round-robin, structurally. A large tenant cannot stretch
  another tenant's interval, because slices are per installation.
- **Budget** — the per-installation slice, denominated in **REST calls, not
  repos**. A repo with 1000 open PRs costs 10 paginated calls; a repo-count
  budget understates real spend by up to 10×. Per-installation is also the unit
  §1.4's rate limit is actually enforced in.
- **Safe interruption** — stamping per repo. A timeout, a reap, or a rate-limit
  backoff means fewer repos stamped, never a lost region. This is the property
  that makes the design correct under both the Job deadline and backoff, and it
  is the one worth protecting above the others.

### 4.3 Error backoff

Under staleness ordering a permanently broken repo stays maximally stale and
would consume its slice on every single run — a self-inflicted denial of the
sweep. Each repo carries `last_error_at` and a consecutive-failure count;
failures back the repo off exponentially so a broken repo cannot monopolize.
Today's behaviour on an unreadable repo is `continue` with a log line
(`worker.py:560-565`); that stays, plus the stamp.

### 4.4 Two entry points, only one budgeted

`reconcile_installation` is **also** called directly, unbudgeted, from
`_record_installation` on `installation.created` (`api.py:2242`), where a brand
new tenant must be swept **completely** rather than given a slice.

The budgeted sweep and the install-time sweep must stay separate entry points.
Folding them together silently gives new installs partial coverage — a
regression that would look exactly like correct behaviour.

### 4.5 Schema (migration 13)

Per-(lane, repo) sweep state. Two lanes with different cadences and different
costs must not share one timestamp, or one lane's sweep hides the other's
staleness.

Carried per (lane, `github_repo_id`): `last_swept_at`, `last_error_at`,
`consecutive_failures`. A separate `repo_sweep_state` table is preferred over
columns on `installation_repos`: it keeps lane-specific scheduling state out of
the tenancy table that `active_repos` and the `?repo=` authorization path both
read, and it lets a lane be added without touching tenancy.

Forward-only. Existing repos start with `last_swept_at` NULL, which sorts
first — so the first run after deploy sweeps the never-swept set, which is the
correct cold-start behaviour.

---

## 5. D5 — the startup sweep keeps a bounded pass *(decided 2026-08-17)*

D2 moves the full sweep out of the startup thread. On its own that is a
**latency regression on the healing property**: today a lost webhook delivery
heals on the next cold start — minutes on a busy service — and afterward it
would wait for the Job's cadence (6h, if the review lane mirrors
`doug-outcome-reconciler-6h`).

**Decision: (b).** The startup thread keeps a *bounded* pass over the stalest
N repos, and only that. It is cheap, and it is reap-safe by construction rather
than by care — §4.2's "stopping early is always safe" property is exactly what
makes a thread that may be killed at any moment a legitimate caller. So the
cost is one extra call site, not new machinery, and the healing latency the
current design has is preserved.

This makes the primitive's interruption-safety load-bearing in two places
rather than one, which raises the value of the interruption test in §6 — that
test now protects the startup path as well as the Job.

Rejected:

- **(a) Accept the regression.** Defensible — reconcile is a catch-up lane and
  the webhook is the latency path — but it trades away a property the system
  has today for nothing, when keeping it costs one call site.
- **(c) Shorten the Job cadence** for the review lane. Pays for healing latency
  with REST calls against every installation on every run, rather than with a
  bounded pass on the instance that just started.

Note the startup pass and the `installation.created` sweep (§4.4) are
different: the startup pass is bounded, the install-time sweep must not be.
That makes **three** call sites into the sweep — bounded (startup), budgeted
(Job), and unbounded (install-time) — and §6's entry-point test must cover all
three.

---

## 6. Testing

The defects here are all "passes for the wrong reason" shaped, so each property
gets a test that can fail:

- **Coverage:** with `N` repos and slice `B`, every repo is swept within
  `ceil(N/B)` runs. Fails if any repo is skipped — the §1.3 defect, pinned.
- **Interruption safety:** kill a run mid-sweep; assert the next run resumes on
  unswept repos and does not re-sweep stamped ones. Pins §4.2's **safe
  interruption** property (the fourth), which D5 made load-bearing for two call
  sites rather than one — the Job's deadline and the reapable startup pass.
- **Fairness:** one 10k-repo tenant and one 5-repo tenant; assert the small
  tenant's sweep interval does not degrade with the large tenant's repo count.
  This is the assertion that would have failed under global ordering (§4.1),
  and it is the one that closes MT3 as written.
- **Budget unit:** a repo with 1000 open PRs consumes 10 calls of budget, not 1.
- **Backoff:** a permanently failing repo does not consume its slice on every
  run.
- **Three entry points, three bounds:** `installation.created` sweeps every
  repo of the new installation ignoring the slice (§4.4); the Job sweeps to its
  per-installation budget (§4.2); the startup pass sweeps at most stalest-N
  (§5). A test per call site — collapsing any two is the §4.4 regression that
  would look like correct behaviour.
- **Lane independence:** sweeping the review lane does not advance the outcome
  lane's staleness.

---

## 7. Out of scope

- **MT0.** Production holds zero `installations` rows, so both sweeps are
  structural no-ops today (`api.py:123-131` prints a DRIFT line naming MT0). MT3
  does not fix that and is not blocked by it: fixing MT0 *exposes* MT3 rather
  than causing it. MT0 is operational — redeliver the `installation` event.
- Changing `drain`'s bound or triggers (D3).
- Cross-lane rate-limit budgeting. §1.4's ordering constraint is respected, not
  re-engineered; a shared per-installation call ledger across both lanes is a
  follow-up if the lanes start contending in practice.
- `_MAX_OPEN_PRS_PER_REPO` and `_MAX_CLOSED_PRS_PER_REPO` keep their current
  values and meaning.
