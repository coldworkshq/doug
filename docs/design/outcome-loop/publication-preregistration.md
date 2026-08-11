# Publication pre-registration — the outcome loop

**Status:** LOCKED v9 — 2026-08-11
**Roadmap:** M3 item 7 · **Mitigation:** design-lock altitude O3 (`design-lock.md:61`)
**Companion:** `60-day-backfill-runbook.md` — the production catch-up is a hard
operational gate before the first 14-day publication (`design-lock.md:47`). The
runbook and this lock are built on `m3-60-day-backfill`; neither the catch-up nor
the v9 hash deployment has occurred in production.

**Changelog.** v1 failed review: the miss rate was not computable, the censoring
arithmetic ran opposite to its own stated direction, "within the window" had no
predicate, "cleared" named no verdict, and the unit contradicted itself. v2 rewrote
it at query altitude and closed those, then failed review again on four things — a
published column no query can produce, a numerator left in prose while the
denominator got SQL, two dispositions that both match the same job, and a
decidability rule that could only ever fire in Doug's favour. v3 fixed those and
folded in fifteen smaller corrections; review three closed 17 of 19 and found one
blocker plus two riders. v4 closes them: `outcomes` has no job discriminator, so the
numerator's join could not enforce the one-row rule it stated; `pending` was
published while its definition had been deleted; and the excluded merges' revert
count was being withheld though it is already in the ledger. **v5 is the first
revision driven by building against the document rather than reading it** — §6.1's
window predicate turned out to have no lower bound, a defect three review rounds
missed. The house template is `survival-probe-1-preregistration.md`: exact formulas,
exact floors. **v6 records the 2026-08-07 rulings** — the window lower bound, the
two-sided decidability rule, the cadence, and the attempts ceiling. **v8 changes
the mechanism, not the published metric:** future merges permanently receive the
14- and 60-day rows in one atomic write, and one guarded historical
`INSERT ... SELECT` fills only missing 60-day siblings. The metric, windows,
censoring, cadence, and denominator are unchanged. **v9 adds one disclosure** —
§2.7's `remediated_clears` and `remediated_revert_count`, published beside the
cleared rate as §3 requires. Nothing is removed, no denominator moves, and
§2.1's governing rule is untouched: the cleared band still contains exactly
what it contained under v8, now with a count of how much of it was repaired
after a flag. §12's free list is cadence-only and does not cover a disclosure
addition, so this is not claimed as free; it is permitted by §12's general
rule that *amendments are permitted; silent ones are not*, and it is
unbounded because §12 restricts only the shrinking direction — this direction
adds disclosure and can only widen what a reader sees. Zero adjudicated rows
existed when v9 was locked, so no published row was ever governed by v8 and
no two-hash publication is created by this amendment.

---

## 0. What this document is for

Doug's third rule is *publish the miss rate, every quarter, including the incidents
that came from PRs it cleared* (`README.md`). A miss rate published on definitions
chosen after seeing the data is a marketing claim.

**The test this document must pass:** two honest engineers, given the same ledger and
this document, publish the same number.

**A stronger test, added in v3 because v2 failed it:** no rule in this document may
be asymmetric between the favourable and unfavourable result. A pre-registered
escape hatch is worse than a post-hoc one, because it fires without anyone noticing.

**A third test, added in v5 because reading could not catch what building did:**
every predicate must be checked against a case it should REFUSE, not only against
cases it should accept. §6.1 survived three reviews because everyone — including two
adversarial passes — read it forward, asking whether a real revert falls inside the
window. Nobody read it backward and asked what else satisfies it. A revert dated
before the merge does, and this repo had already measured that at 9–11% of labels.

**The commitment is not "our number will be good." It is: this number, on these
definitions, on this date, whatever it says.**

---

## 1. Unit of analysis

**The unit is `(repo, window)`. There is no pooled rate, ever.** A quarterly
publication is a table of per-repo rows, not a headline number. Pooling across repos
with different base rates produces a number describing no population
(`product-spec.md:48` bans cross-repo aggregate copy). A sum of counts may be shown;
a pooled rate may not.

Doug-on-Doug (`drewjst/doug`) always appears.

**RULED (Andrew, 2026-08-07): tenant repos are IN BY DEFAULT, by name, and may opt
out.** Not opt-in — a tenant appears unless they say otherwise.

**The publication is an audit of Doug, not of its customers.** Doug-on-Doug is the
row that discharges the commitment: the repo is public, anyone can run `git log`
against it, and it needs nobody's permission. Tenant rows are corroboration, never
the basis — so a quarter in which every tenant has opted out is still a valid
publication, and the commitment is never hostage to sales.

**Opt-out is PROSPECTIVE ONLY, and this is the property the whole posture rests on.**

- Withdrawal removes **future** windows. It cannot retract a window already elapsed.
- **A published row is never retracted.** A repo that leaves keeps its existing rows
  in every subsequent publication; departure ends the series, it does not erase it.
- `repos_withheld` publishes as a count, so an opted-out set can never pass for
  nobody having left.

Without the second bullet the posture would quietly invert into the failure §2.4
names: tenants with bad rates leave, tenants with good ones stay, and the standing
table drifts favourable one departure at a time while every individual decision looks
reasonable. Keeping departed rows published is what makes the record cumulative
rather than a snapshot of whoever is currently comfortable.

**A product requirement falls out of this ruling and is stated here so it cannot be
lost:** because the default is IN, the install flow must disclose — unmissably, not
in a link — that the installation's cleared-band rate may be published by name on a
public page, and how to opt out. A default that discloses is only honest if the
disclosure actually reaches the person accepting it. Naming a tenant's defect rate
publicly is a real disclosure about them, not only about Doug.

**Anonymized rows were rejected.** At M5's 2–3 design partners "Repo B" is not
anonymous — a partner is identifiable from merge counts alone — and it manufactures
an impression of breadth adjacent to the cross-repo claim `product-spec.md:48` bans.

---

## 2. The denominator

### 2.1 The band-membership rule

A PR has one verdict **per head sha** (`migrations.py:185-187` makes uniqueness
`(installation_id, github_repo_id, pr_number, head_sha)`), so a PR pushed five times
has five verdicts, which may straddle the threshold.

**The governing verdict is the one with the greatest `scored_at` at or before
`outcome_jobs.merged_at`** — the advice standing when a human chose to merge. Ties
on `scored_at` break to the greatest `verdicts.id`.

Qualifying: `tier = 'reader'` and `band = 'cleared'`. Deterministic-tier verdicts are
governed by §2.5, not this rule; `tier='external'` rows are §7's secondary metric.
`design-lock.md:77`: deterministic ranking "is not the product … it is the loud,
labeled fallback."

> **Two honest limits.**
> **(a) The merged head sha is not stored.** The obvious rule — "the verdict on the
> head sha that was merged" — is uncomputable: `outcome_jobs` stores
> `merge_commit_sha`, a different commit on a squash merge, and the PR's head sha at
> merge is stored nowhere. Adding it is a follow-up (§11). `scored_at <= merged_at`
> is what the schema supports, pinned here so the choice cannot later be made in
> whichever direction flatters.
> **(b) The comparison straddles two clocks.** `merged_at` is GitHub's
> (`api.py:1047`); `scored_at` is Doug's Cloud Run clock — `save_review` hardcodes
> `datetime.now(UTC)` (`store.py:505`, and `store.py:588` says so outright). A
> near-simultaneous score-and-merge resolves on skew. See §2.4, which is where that
> lands.

### 2.2 The denominator query

```sql
-- N_done: adjudicated cleared-band merges, one repo, one window.
WITH ranked AS (
  SELECT v.installation_id, v.github_repo_id, v.pr_number, v.band, v.id,
         row_number() OVER (
           PARTITION BY v.installation_id, v.github_repo_id, v.pr_number
           ORDER BY v.scored_at DESC, v.id DESC
         ) AS rn
  FROM verdicts v
  JOIN outcome_jobs j
    ON  j.installation_id = v.installation_id
    AND j.github_repo_id  = v.github_repo_id
    AND j.pr_number       = v.pr_number
  WHERE v.tier = 'reader'
    AND v.scored_at <= j.merged_at
    -- Same filters as the outer query, so the CTE is self-evidently correct
    -- rather than correct-by-argument. Future 14- and 60-day rows are one
    -- atomic write; the historical insert-select copies the 14-day facts.
    AND j.window_days = :window
    AND EXISTS (
      SELECT 1 FROM installations i
      WHERE i.installation_id = j.installation_id
    )
),
governing AS (SELECT * FROM ranked WHERE rn = 1)
SELECT count(DISTINCT j.pr_number)
FROM outcome_jobs j
JOIN governing g
  ON  g.installation_id = j.installation_id
  AND g.github_repo_id  = j.github_repo_id
  AND g.pr_number       = j.pr_number
WHERE j.status        = 'done'
  AND j.window_days   = :window
  AND j.github_repo_id = :repo_id
  AND EXISTS (
    SELECT 1 FROM installations i
    WHERE i.installation_id = j.installation_id
  )
  AND g.band          = 'cleared';
```

`row_number()`, not `DISTINCT ON` — the latter is Postgres-only and **every test in
this project runs sqlite** (`REVIEWING.md:141-143` records that exact trap). The most
load-bearing query in this document must be exercisable by the suite that guards it.

`count(DISTINCT j.pr_number)`, not `count(*)`: `uq_outcome_job` includes
`merge_commit_sha` (`store.py:293-300`), so two rows for one PR at one window are
schema-permitted.

`count(outcome_jobs …)`, **never `count(outcomes)`** (`design-lock.md:14`) —
`outcomes` is append-only and one merge can carry several rows.

### 2.3 The numerator query, and the one-row rule

v2 gave the denominator SQL and left the numerator in prose. Two implementers could
therefore disagree about which `outcomes` row is authoritative for a job.

**Rule: `adjudicate.py` writes exactly ONE classification row per `outcome_jobs` row**,
`kind ∈ {revert, clean, censored}`. `hotfix` is never written by the adjudicator
(§10).

> **`outcomes` needs a job discriminator, and migration 007 must add it.** §2.2
> defends against two `outcome_jobs` rows for one PR at one window — `uq_outcome_job`
> includes `merge_commit_sha` (`store.py:293-300`), so that is schema-permitted. But
> `outcomes` carries **no merge sha and no job id**: its columns are `id, repo,
> pr_number, kind, observed_at, source, github_repo_id, installation_id,
> window_days, detail` (`store.py:111-130`). A per-job rule cannot be joined on a
> per-(PR, window) key. Concretely: PR #412 with two jobs at window 14, the
> adjudicator obeying the one-row rule perfectly, job A → `revert`, job B → `clean`.
> Then `N_done = 1` while `misses = 1` and `clean = 1`, the identity below is false,
> and one PR publishes as both a miss and a survival.
> **Migration 007 adds `merge_commit_sha` to `outcomes`** (§11), and it joins on it.

```sql
-- misses: the numerator. The one-row rule is ENFORCED here, not assumed.
WITH adjudication AS (
  SELECT o.*, row_number() OVER (
           PARTITION BY o.installation_id, o.github_repo_id, o.pr_number,
                        o.window_days, o.merge_commit_sha
           ORDER BY o.id
         ) AS rn
  FROM outcomes o
)
SELECT count(DISTINCT j.pr_number)
FROM outcome_jobs j
JOIN governing g ON (…as in §2.2…)
JOIN adjudication o
  ON  o.installation_id  = j.installation_id
  AND o.github_repo_id   = j.github_repo_id
  AND o.pr_number        = j.pr_number
  AND o.window_days      = j.window_days
  AND o.merge_commit_sha = j.merge_commit_sha
  AND o.rn = 1
WHERE (…as in §2.2…) AND o.kind = 'revert';
```

`censored` substitutes `o.kind = 'censored'`; `clean` likewise.

`o.rn = 1` — the **lowest `outcomes.id`** — is the tie-break, and it is in the SQL
rather than in prose, because v2 failed on exactly that gap. It is not arbitrary: the
lowest id is the earliest adjudication, which is §6.1's finality rule applied to a
duplicate. A later correction does not win, for the same reason a later revert does
not reopen a `clean`.

The identity `N_done = misses + clean + censored` holds **because** of the one-row
rule and the join key above, not independently of them.

### 2.4 Merges with no governing verdict

`_record_merge` (`api.py:1033-1080`) writes an `outcome_jobs` row for **every** merged
PR carrying its five required facts. It applies **no** fork gate, **no** draft gate,
**no** verdict-existence check — those live only on the review path. So some merges
have a job row and no governing verdict.

**Ruling: excluded from numerator and denominator, with the count published as
`unverdicted_merges`, broken into named buckets.** An exclusion nobody can see is a
population that can be quietly resized. The buckets, because one aggregate number
cannot be read:

| Bucket | Cause |
|---|---|
| `merged_before_verdict` | The reader verdict exists but `scored_at > merged_at` — auto-merge, a one-line fix, a queue backlog, a cold start. Reviews drain asynchronously (`api.py:1322-1324`). **This is expected to be the largest bucket**, and it removes the fastest-merging, most-routine PRs — a non-random slice of the cleared band, so it publishes separately rather than pooled. |
| `no_verdict_at_all` | Merged fork PRs; PRs opened before install; PRs whose review job failed. |
| `fallback_only` | The only verdict is `tier='deterministic'` → §2.5, **not** counted here. |

v2's list named "drafts merged without review" (GitHub refuses to merge a draft; it
must be marked `ready_for_review`, which is in `PR_ACTIONS` at `api.py:812` and
enqueues a review) and "PRs merged before install" (which produce no webhook at all,
so no job row). Both were wrong; the real dominant case was absent.

**Their revert count publishes too, as `unverdicted_revert_count` per bucket.**
Publishing only the exclusion count would violate §0's anti-asymmetry test, and this
is the clearest instance of it in the document. These merges have `outcome_jobs` rows
— §2.4's first sentence — and nothing filters the adjudicator on verdict existence,
so every one reaches `status='done'` and gets an `outcomes` row. **Their revert count
is already in the ledger and costs one `WHERE` clause to read.** Withholding it can
only ever make the published picture *more* flattering or leave it unchanged: a
reader given `N_at_risk = 300, miss_rate = 0.3%, unverdicted_merges = 900` cannot
tell whether those 900 reverted at 0.1% or at 4%, and the second case would mean the
cleared-band number describes the easy tail of its own population.

§3 already applies exactly this standard to censoring — "because `miss_rate`
describes only the observable subpopulation, `censoring_rate` publishes in the same
table, always." It binds harder here: a censored row genuinely could not be observed,
while an unverdicted merge **has been observed** and the observation is being
withheld.

**This is a disclosure, not a comparator, and it does not reopen `design-lock.md:51`.**
That supersession closed the flagged-vs-cleared comparison because the flagged band
is "contaminated by the intervention itself — flagging causes scrutiny." Unverdicted
merges carry no Doug intervention at all, which is what makes them publishable as a
count — and it is also why they must not be promoted to a headline comparator.

### 2.5 The fallback-tier row

Deterministic-tier clears publish as their own named row in the same table, with the
same construction as §2.2–§2.3 substituting `tier = 'deterministic'`, and the same
`N_at_risk` treatment. They are **not** counted in `unverdicted_merges` and **not**
merged into the primary. `design-lock.md:77`: near-random on repo #2, and we say so
rather than sell it.

### 2.6 Structural exclusions

| Excluded | Executable predicate | Status |
|---|---|---|
| Research/CLI rows | `EXISTS (SELECT 1 FROM installations i WHERE i.installation_id = outcome_jobs.installation_id)` | Structural — prospective App merges belong to the installation registry; research and un-tenanted CLI rows do not. |
| Other tenants | `github_repo_id = :repo_id` | Sound. |
| Non-merged PRs | none needed — `_record_merge` returns before writing (`api.py:1041-1045`) | Structural. |
| 90-day replay | **⚠ UNRESOLVED** | `outcome_jobs` has **no `source` column**. v1 specified `source='replay'`; it is unexecutable. The replay path does not appear to write `outcome_jobs` today. M4 must keep it that way and say so in code, or add a discriminator. §11. |

### 2.7 Remediated clears

A governing-cleared PR (§2.1) is a **remediated clear** when any earlier
verdict on the same identity `(installation_id, github_repo_id, pr_number)`
with `tier = 'reader'` and `scored_at <= merged_at` has `band = 'flagged'`.
§2.1's governing rule is unchanged — the PR stays in the cleared band and in
`N_at_risk` — but its count publishes beside the rate as `remediated_clears`,
with `remediated_revert_count`: a disclosure, never a comparator, exactly as
§2.4 treats `unverdicted_merges`. The cleared band otherwise pools two
populations — never-flagged PRs and flagged-then-repaired ones — with
different expected revert rates, and a pooled rate with no bucket lets
remediation quietly reshape the published population. Not hypothetical:
PR #49 on `drewjst/doug` (reviewed twice, five findings, all fixed, merged
cleared) is already in the band §1 commits to publishing. The rows needed
are already retained — verdicts are append-only and carry `band` and
`scored_at` — so this is a publication-time query, not a schema change.

---

## 3. The published metric

```
misses      = §2.3          clean = §2.3          censored = §2.3
N_done      = misses + clean + censored          (= §2.2, by the one-row rule)
N_at_risk   = N_done - censored
miss_rate   = misses / N_at_risk
censoring_rate = censored / N_done
```

**Censored rows leave the risk set.** They are not scored as successes. v1 left them
in the denominator while claiming censoring "can only tighten" the rate — the
opposite of the arithmetic, in the flattering direction. Rejected: counting censored
as misses, which at 40% censoring yields a "miss rate" of 40% — a censoring rate
wearing a costume.

Because `miss_rate` describes only the observable subpopulation, `censoring_rate`
publishes in the same table, always.

**Zero rules** (both states are reachable — `N_at_risk = 0` for a team that merges to
release branches, `N_done = 0` for any repo's first quarter and every 60-day row
before the backfill):

- `N_at_risk = 0` → publish `misses`, `N_done`, `censoring_rate`, and the literal
  string **"no observable risk set — rate undefined."** No CI.
- `N_done = 0` → the row publishes as counts only. No rates, no CI.

Published together, never separately:

| Column | Definition |
|---|---|
| `N_at_risk`, `misses`, `miss_rate` | §3 |
| Wilson 95% CI | on `miss_rate` at `N_at_risk`; absent when `N_at_risk = 0` |
| `base_rate` | §4 — same repo, **same window** |
| `decidable` | §8 |
| `censoring_rate` | §3 |
| `unverdicted_merges` | §2.4, **by bucket** |
| `unverdicted_revert_count` | §2.4, by bucket — a disclosure, never a comparator |
| `remediated_clears` | §2.7 — count of governing-cleared PRs with an earlier flagged reader verdict |
| `remediated_revert_count` | §2.7 — their reverts; a disclosure, never a comparator |
| `partial_read_share` | §5 |
| `pending` / `failed` | §6.2's second table — job states, not dispositions |
| label-noise estimates | §9, **both directions** |
| `repos_withheld` | §1 |

**Why the cleared band alone.** `design-lock.md:51` superseded the flagged-vs-cleared
comparison: that visual *is* the causal claim the honesty contract forswears, and the
flagged band is contaminated by the intervention — flagging causes scrutiny, so its
revert rate measures Doug's effect on reviewers, not Doug's accuracy.

**Not published:** capture-rate percentages (`product-spec.md:44`); research-corpus
precision alone (ADR-0005 requires CORPUS + POP together); per-author-type rates
(`design-lock.md:73`); any pooled or cross-repo rate (§1).

---

## 4. The base rate

```
base_denominator = distinct PR numbers whose squash merge commit carries a committer
                   date inside the 12 months ending at
                   (publication_date - window_days), enumerated from `_log_records`
                   (git_labels.py:127-148) keeping Commit.date and parsed with the
                   same \(#\d+\) subject rule. The default-branch restriction comes
                   from the clone, not this function: `_log_records` runs
                   `git log --all` (git_labels.py:131-133), and it is
                   `--single-branch` in `clone_treeless` (git_labels.py:97) that
                   makes "all refs" mean the default branch.
base_numerator   = those PRs reverted within THE SAME WINDOW of their own merge
base_rate        = base_numerator / base_denominator
```

Resolutions, each in the direction that does **not** flatter:

1. **The function v2 cited could not do the job.** `pr_numbers_by_sha`
   (`git_labels.py:151-159`) returns `dict[str, int]` and **discards `c.date`** — it
   cannot support a 12-month filter or a per-PR window. `_log_records` carries
   `Commit.date` and is the correct source.
2. **Distinct PR numbers**, not commits. `len(dict)` and `len(set(values))` differ.
3. **Revert PRs are NOT excluded — from either side.** v3 excluded them here and
   could not exclude them from §2.2, which is a ledger query with no access to commit
   subjects. That produced a comparator over a different population than the metric:
   a revert PR that Doug cleared gets an `outcome_jobs` row like any other merge
   (`_record_merge` has no subject filter) and counts in `N_at_risk`. **Alignment
   beats purity here** — an unaligned comparison is wrong in an unknown direction,
   since nobody knows whether revert PRs revert more or less often than ordinary
   ones. Both sides now include them.
4. **The tail is truncated at `publication_date - window_days`.** PRs merged inside
   the last window have not had a full window to be reverted. `N_done` already
   excludes immature merges (`pending` is not `done`), so an untruncated base
   denominator would compare a matured Doug rate against an unmatured comparator.

**Same window is mandatory** — an unbounded-horizon 12-month rate against a 14-day
cleared rate inflates the comparator. v1 omitted this.

**Disclosed population difference, not merely a recall limit.** The comparator is
drawn from **squash-merged PRs only**, while the metric is drawn from **all merges**
the webhook saw. On a mixed-merge-style repo these are different populations and the
direction of the resulting bias is unknown. §9 discloses squash conditioning for
attribution *recall*; this is the separate, denominator-level version of it, and it
publishes with the rate.

---

## 5. Coverage, and a column that cannot be published yet

**Partial reads are INCLUDED in the denominator.** Excluding them would be the escape
hatch: the unread part of a diff is exactly where an unfound defect lives.

**`partial_read_share` is NOT PUBLISHABLE until migration 007 lands**, and publishes
as "not available" until then — the same treatment §6.3 gives the 60-day row.

The reason, found in review: `Coverage.complete` is a **computed property**
(`reader.py:434-441`), `sent_chars >= diff_chars and not files_dropped`. The `reads`
table has five data columns — `diff_chars, sent_chars, files_sent, files_unseen,
file_cut` (`store.py:141-151`) — and `save_read` (`store.py:892-906`) writes exactly
those. **`files_dropped` is never persisted.** From the ledger only
`sent_chars >= diff_chars` is reconstructible, so computing the share the schema's
way silently drops the `files_dropped` half — and `REVIEWING.md:428-438` is explicit
that the dropped-file case is the one that "should have been reviewable and was not."
An understated partiality share, biased toward the reads most likely to hide a
defect, is the flattering direction.

**Required: migration 007 adds `files_dropped` and `changed_files` to `reads`** (§11).
`reads` is an existing table, so this is a migration, not a `create_all` addition —
the reason that table exists at all (`store.py:132-140`).

---

## 6. Windows, dispositions, job states

### 6.1 The window predicate

```
merged_at_utc - timedelta(days=TOLERANCE_DAYS)
    <= revert_instant_utc
    <= merged_at_utc + timedelta(days=window_days)
```

Inclusive at the boundary. **Both sides are timezone-aware instants parsed from
`%cI`, never the raw strings.**

> **RULED (Andrew, 2026-08-07): the lower bound is adopted at `TOLERANCE_DAYS = 1`.**
> Recorded in full because the reasoning is the ruling, not the number.
> Found by building against this document, which three review rounds had called
> buildable. A revert commit dated *before* `merged_at` satisfies it and publishes
> as a miss for a PR it predates.
>
> **It is not a hypothetical, and this repo has already measured it.**
> `scripts/label_precision_delta.py:3-6`: *"A revert cannot land before the PR it
> reverts. Some do in our label set — **6/67 on sentry, 6/54 on grafana** at >1 day
> — because `pr_titles_from_subjects` is newest-wins, so a revert of an older PR
> with a reused title gets attributed to a newer one."* That is 9% and 11% of the
> labels on the two corpora that validated the detector. The mechanism is a reused
> squash title (a dependency bump, "Fix typo"), not a doctored clock.
>
> **The live and backtest paths currently disagree, which `design-lock.md:29`
> forbids.** `scripts/screen_features.py` and `scripts/rf_kamei.py` dropped these
> labels at their own `TOLERANCE_DAYS = 1` while the adjudicator applied no bound at
> all, and `scripts/backfill_ledger.py` writes the *filtered* set into `outcomes`. So
> "live labels and backtest labels are the same event" — the whole reason
> `git_labels.py` is the only detector — was false.
> **CLOSED by this ruling:** the constant now lives once, at `git_labels.py:51`, and
> both sides import it. Those scripts' own definitions are gone, which is why this
> paragraph no longer cites them by line.
>
> **Why this is Andrew's call and not an editorial fix.**
> `label_precision_delta.py:13` said of its own output: *"This prints every headline
> number both ways. **It decides nothing.**"* The repo deliberately left the
> question open, and the adjudicator is what forces it. Two live considerations:
> the script's tolerance exists because *"sub-day negatives are committer-date vs
> `merged_at` skew on same-day reverts, not mislabels"* (`:75-77`), so a strict
> `>= merged_at` would itself diverge from the backtest; and the detector is
> **partial** — it catches only collisions with an *older* PR, because *"a collision
> with a newer one produces positive lag and stays invisible"* (`:9-10`).
>
> **The ruling.** `TOLERANCE_DAYS = 1` is hoisted out of `scripts/` into
> `git_labels.py`, so the live path and the backtest read ONE constant and
> `design-lock.md:29`'s "same detector both sides" becomes true again rather than
> aspirational. Not zero: sub-day negatives are committer-date vs `merged_at` skew
> on same-day reverts, not mislabels (`label_precision_delta.py:75-77`), so a strict
> `>= merged_at` would itself diverge from the backtest — the opposite error.
>
> **What this ruling costs, stated because it is the unflattering half.** Dropping
> impossible labels REMOVES misses from the numerator, so it can only lower the
> published miss rate. It is adopted because the alternative is publishing a rate
> that counts reverts against PRs they predate, not because it is favourable — and
> the count of labels dropped this way publishes with the rate, so the effect is
> visible rather than absorbed.
>
> The invisible positive-lag half is disclosed in §9.

> **A declared amendment to the detector, not a reuse of it.** The backtest keeps
> raw `%cI` **string** comparison — `candidate.date < incumbent.date`, in
> `_earlier_by_string` (`git_labels.py:237-241`). Across differing UTC offsets,
> string order is not chronological order, so "earliest wins" is not guaranteed to
> pick the earliest *instant*. The adjudicator's parser passes `_earlier_by_instant`
> instead (`git_labels.py:243-256`), which compares parsed instants and breaks ties
> on sha. Both predicates feed one shared attribution pass (`_attribute_reverts`,
> `git_labels.py:260-318`), so the two paths differ in exactly that argument rather
> than in two hand-maintained copies — "same detector both sides" is a property of
> the code, not a promise. §10 states how the amendment is pinned.
>
> Before the M3 refactor this comparison lived inline in `mark()`; this paragraph
> described that shape and was updated when the code moved, not left to rot.

**An adjudication is final.** A revert discovered afterwards does not reopen a
`clean`. The window test is on the revert's own timestamp, not on when the
adjudicator drained, so a late drain (backlog, Scheduler outage, retries) cannot move
a label. The cost of finality is a false-negative class, disclosed in §9.

### 6.2 Dispositions (in precedence order), and the job states that are not dispositions

**Precedence is stated because v2's dispositions were not mutually exclusive.** A PR
merged to `release-2.4` whose revert is cherry-picked to the default branch matches
both `revert` and `censored`: attribution reads only the revert commit's subject
(`git_labels.py:301-307`) and never checks where the original landed, while the clone
is `--single-branch` on the default branch (`git_labels.py:97`) — so this is exactly
the case the detector *can* see. `design-lock.md:15` forbids `clean` there; it does
not arbitrate between `censored` and `revert`.

**Dispositions** — `outcomes.kind`, written only for a job the adjudicator actually
evaluated. Precedence 1→3 is total and mutually exclusive: `base_ref` either is the
cloned default branch or is not, so 2 and 3 partition, and 1's precedence resolves
the single overlap.

| # | `kind` | Condition | In `N_done`? |
|---|---|---|---|
| 1 | `revert` | §10 attribution inside §6.1's window — **checked first** | yes |
| 2 | `censored` | `base_ref` is not the cloned default branch; **or** the repo is permanently unreachable (uninstalled, deleted) | yes, then removed from `N_at_risk` |
| 3 | `clean` | neither of the above, `base_ref` **is** the default branch | yes |

**Job states that are not dispositions** — `outcome_jobs.status`
(`store.py:289-290`), a different column. Neither is a `kind`, and a `failed` job
never entered the precedence chain above, so it is not "fourth" in it. v3 listed it
as a fourth disposition, which conflated the two vocabularies and left `pending`
undefined while §3 still published it.

| `status` | Condition | In `N_done`? |
|---|---|---|
| `pending` | `due_at` has not elapsed | no — counted and published |
| `failed` | adjudicator errored, attempt ceiling exhausted | no — counted and published |

**Attribution wins over censoring.** An observed revert is evidence we *did* see;
censoring is for blindness. Checking `base_ref` first would let a real, visible miss
be removed from the risk set and *lower* the published rate — the flattering
direction, and the whole reason precedence is stated rather than left to the
implementer.

**Retry before censoring.** A clone failure is an adjudicator error, not blindness
about the repo: it retries to the attempt ceiling and lands `failed`.

**RULED (Andrew, 2026-08-07): `max_attempts = 10`, deliberately higher than the
review path's 3** (`ingest.fail`). The two ceilings bound different things and
should not match. A review retry buys a MODEL READ, so 3 is a spend guard; an
adjudication retry buys a `git clone` and costs effectively nothing, so the ceiling
is free to be generous. What it protects is the published denominator: every job
that exhausts its attempts leaves `N_done` entirely (§6.2), and a transient
GitHub outage that burns 3 attempts across three scheduled runs would silently
shrink the population a rate is computed over. 10 makes that need a sustained
failure rather than a bad afternoon.

**Revisit when the Scheduler cadence is set** (M3 item 2): the ceiling is in
attempts, but what it buys is wall-clock, and 10 attempts means something different
at hourly than at daily. The number is pinned here; its adequacy is not decidable
until the cadence exists.

> `design-lock.md:15` sanctions only `base_ref` censoring. Permanent-unreach
> censoring is an addition made here, declared so the lock and this document do not
> drift.

### 6.3 Both windows

14 and 60 days, both from `merged_at`. The 14-day window over-samples fast, loud
failures — flaky-bug median detection is 34 days (arxiv.org/pdf/2103.11518).

Independent rows, independent denominators, **never summed** (`uq_outcome_job`
includes `window_days`).

**Future merges receive both rows atomically.** `_record_merge`
(`api.py:1073-1080`) calls `store.enqueue_outcome_jobs`, which prepares the 14- and
60-day rows from the same stored merge facts and commits them in one multi-value
statement. A redelivery may fill a missing sibling but cannot add a second row at
either window. The one-time historical backfill (`design-lock.md:47`) is narrower:
it copies stored facts only from registered 14-day rows whose 60-day sibling is
missing. Until that production catch-up runs, the publication carries an explicit
**"60-day: not yet available"** line — it does not silently become a 14-day-only
report.

---

## 7. The secondary metric: the neutral-grader lane

v2 deleted this and left a cross-reference pointing at a section that no longer
discussed it. Restored, because it is a locked red-team mitigation
(`design-lock.md:59`, altitude O1 — "Doug becomes the neutral grader, which is the
uncontested lane") and a live public claim (`product-spec.md:38`: "Every verdict —
ours and your reviewers' — is adjudicated").

Same clock, same detector, same windows, **reported separately and never merged into
the primary** — a different population and a different claim.

**Unit: `(reviewer, PR)`.** A PR may carry several reviewers' stances; each is graded
on its own.

**Disclosed limit:** `save_external_review`'s dedup is a SELECT, not an index —
`store.py:609-612` records that "two genuinely concurrent deliveries of one review
can both read before either commits, and both insert", so one reviewer's stance can
be counted twice. The publication states the duplicate rate or the metric is void.

---

## 8. Decidability, and the floor

**RULED (Andrew, 2026-08-07): the two-sided rule below is adopted.** v2's
proposed rule was defective and is withdrawn; the history stays because a
withdrawn rule that leaves no trace is indistinguishable from one that never
existed.

v1 proposed `N ≥ 30`, stated in merges but justified with grafana math about
*defects* (`design-lock.md:84`). At 150 merges/month a denominator of 30 arrives in
about six days, so it gated nothing. Worse, at `N_at_risk = 30` with zero misses the
Wilson 95% upper bound is ≈ **11.4%** against base rates of 0.37%–1.34% — it cannot
decide the comparison it exists for.

**v2 then proposed:** label a row `decidable` only when the Wilson upper bound falls
**below** `base_rate`. **That rule is one-sided and is withdrawn.** At
`N_at_risk = 400, misses = 20` the cleared band is decisively *worse* than the repo
average — the most important result this instrument could produce — and the upper
bound is not below `base_rate`, so v2's rule would have labelled it *"not yet
decidable, this is a count, not a rate."* A pre-registered rule that fires only
toward the favourable conclusion is worse than a post-hoc one.

**The rule, two-sided:** `decidable` when the Wilson 95% interval **excludes
`base_rate` in either direction**, with the direction named in the copy:

- `UB < base_rate` → **"cleared band safer than this repo's average."**
- `LB > base_rate` → **"cleared band WORSE than this repo's average."**
- interval contains `base_rate` → **"not yet decidable — a count, not a rate."**

**`base_rate` is treated as a known constant**, not as an estimate with its own
interval — §4 computes it over 12 months against a window of at most 60 days, so its
N is far larger and its interval far tighter. This makes `decidable` fire marginally
too readily in **both** directions, so it does not violate §0's test; it is stated
because Andrew is being asked to ratify the rule, not to discover its assumptions.

**A residual asymmetry that runs against us, and is kept.** At a 0.37% base rate,
"safer" needs `N_at_risk` in the high hundreds (rule of three: `UB ≈ 3/n < 0.0037`
→ `n > 810`), while "worse" is reachable near `n ≈ 100` with three misses. Bad news
becomes decidable far earlier than good news. That is a property of the binomial
rather than of the rule, and it points the right way.

Publish at any N regardless. Three post-hoc moves stay forbidden under any ruling:
**do not** delay to accumulate N, **do not** widen the window to reach N, **do not**
pool across repos to reach N.

Low-base-rate repos may sit undecidable for close to a year; the install-time
projection discloses that before install (`product-spec.md:17`).

---

## 9. Stated label noise — both directions

**False positives (inflate the rate).** Reverts fire for feature flags, dependency
conflicts, release mechanics (arxiv.org/abs/2509.09192). Basis: hand audit of every
revert in the window, classified defect / not-defect.

**False negatives (deflate the rate).** v1 omitted these entirely:

- The detector is conditioned on a **squash-merge convention** (`git_labels.py:3-6`);
  on a merge-commit repo, attribution degrades.
- Attribution recall is below 100% even on a validated repo — on grafana the title
  fallback alone resolved **64%** of reverts (`git_labels.py:273-275`).
- Every ambiguous short sha resolves to nothing (`git_labels.py:162-171`).
- **Title-collision attribution is one-sided.** `pr_titles_from_subjects` is
  newest-wins, so a revert of an older PR with a reused title is attributed to a
  newer one. §6.1's proposed lower bound catches the half that lands *before* the
  merge; a collision with a newer PR "produces positive lag and stays invisible"
  (`scripts/label_precision_delta.py:9-10`). The true PR gets no label at all, which
  is a false negative regardless of how ruling 5 lands.
- **Finality (§6.1):** a revert whose committer date falls inside the window but
  which reaches the default branch after the adjudicator drained is permanently
  invisible. The finality rule is correct and worth keeping; its cost belongs here.

Basis: the same hand audit counts reverts in `git log` the detector failed to
attribute, and publishes **attribution recall**.

**This is a recurring cost, not a free one.** v2 claimed it "costs nothing extra"
because M3's exit gate already requires a `git log` audit — but that gate
(`ROADMAP.md:269-272`) is a **one-time** audit of **one repo** as a build gate, while
this is one hand audit per published `(repo, window)`, every quarter, forever.
Calling it free is what makes it skippable later. **A publication without both noise
estimates is a void publication under §12.**

**We do not correct the rate for noise.** Rate and estimates publish side by side.

---

## 10. What "reverted" means

**Same detector both sides** (`design-lock.md:15`, `:29`) — live labels and backtest
labels must be the same event, or the published rate is not comparable to the
validated evidence it will be quoted beside.

**Reverted** = the detector attributes a revert commit to the PR, its instant
satisfies §6.1, and its sha is recorded in `outcomes.detail` and the receipt.

> **The sha requires a detector amendment.** `parse_revert_targets_dated` returns
> `dict[int, str]` — PR → date; **the reverting commit's sha is discarded**
> (`git_labels.py:260-318`). But `design-lock.md:15` requires `detail` carry "anchor
> sha, revert sha" and `product-spec.md:39` requires "a revert commit we can point
> to (sha in the receipt)". The adjudicator uses a **sha-retaining variant**: same
> predicate, same dates, sha kept. "Verbatim" was the wrong word and v1 used it.
> **Which sha survives:** the sha of the commit whose instant won `mark()`; ties on
> instant break to the lexicographically smallest sha. Unstated, this diverges on
> exactly the re-revert case the detector calls out — one implementer publishes the
> day-3 revert's sha, another the day-40 re-revert's, and that sha is the one
> artifact a customer checks by hand.

Detector semantics, stated because "reverted" sounds more self-evident than it is:

- **The commit subject gates.** A `This reverts commit <sha>` body marker alone is
  not enough — "Reland X" carries one and is the opposite of a revert
  (`git_labels.py:177-178`, `:277-279`).
- **All three attribution paths apply — this is not a precedence chain.** Nested
  `#N`, body-sha pointer and quoted-title lookup each call `mark()` unconditionally,
  with no `elif` and no early return *between the three paths*
  (`git_labels.py:301-318`; the `continue` at `:313` separates the two subject forms,
  not the paths). **One revert commit may attribute to several PRs**, and a quoted
  title colliding with an unrelated squash title marks both. Accepted for corpus
  comparability; the collision rate is measured by §9's audit. When one commit marks
  two PRs, both receipts carry the same sha — correct, and stated.
- A short sha resolves only on an **unambiguous** prefix (`git_labels.py:162-171`).
- **The date is the reverting commit's** — nobody, including a live Doug, could have
  known the PR was bad before the revert landed.
- On a re-revert the earliest instant wins (subject to §6.1's amendment).

**Survived** = no attributed revert inside the window. Nothing more
(`product-spec.md:39`). Not "validated", "safe" or "endorsed" — survival is *not yet
detected*.

**`hotfix` is not a miss** and is never written by the adjudicator (§2.3). It exists
in `outcomes.kind` (`store.py:117`) and no detector here distinguishes "hotfix
repairing this PR" from "hotfix that merely followed it."

### The enforcement this document depends on

`adjudicate.py` and ROADMAP M3 item 1 shipped in #59. Its committed fixtures make
the live-≡-backtest gate executable, including the differing-UTC-offset case and
the detector cases named below. The scheduled database/GitHub path is built on
`m3-adjudicator-job`; production execution remains an operational gate.

**This document does not take effect until that test is green.** Nothing publishes
under it before then. Two things are required by name, because a test that cannot run
makes the gate unsatisfiable and a test on single-offset fixtures makes it vacuous
(`REVIEWING.md:119`: "a property whose every test input is drawn from the same
assumption the code makes survives every mutant"):

1. **A committed fixture with at least one pair of revert commits whose UTC offsets
   differ such that string order and instant order disagree**, asserting the parsed
   path picks the earlier instant. The backtest corpus is gitignored
   (`.backtest-cache/`) and cannot serve as a CI fixture.
2. **The corpus-equivalence run as an operator-run gate**, with its result recorded
   in this document's lock commit — the pattern ADR-0012 already uses for its pinned
   read-budget numbers — not a CI job that silently never runs.

---

## 11. Open rulings (⚠) and required work

**All five ruled 2026-08-07** — recorded here so the list stays the index of what was
decided, with each ruling's reasoning in its own section.

1. **Tenant consent posture** (§1) — tenant repos are **in by default, by name**, and
   may opt out prospectively. A published row is never retracted, which is the
   property that stops departures from drifting the table favourable.
2. **Decidability** (§8) — two-sided rule adopted. v2's one-sided version withdrawn.
3. **Cadence, venue, first date** (§12) — quarterly 15 Jan/Apr/Jul/Oct as a FLOOR,
   venue and provisional 15 Jan 2027 accepted. Publishing sooner or more often is
   free; off-cycle publications must carry the full table; only lengthening or
   skipping is prospective-only.
4. **The `outcome_jobs.attempts` ceiling** (§6.2) — `max_attempts = 10`, higher than
   the review path's 3 because an adjudication retry buys a clone, not a model read.
5. **The window's lower bound** (§6.1) — adopted at `TOLERANCE_DAYS = 1`, hoisted
   into `git_labels.py` so live and backtest read one constant. **The only ruling
   that changes a published number**, and it lowers it.

**The lock prerequisites are complete:** the §10 fixture gate shipped green in M3
item 1 (#59), migration 007 and the bounded Cloud Run Job/Scheduler are live, and
`60-day-backfill-runbook.md` now records the guarded repair. **Only the production
catch-up remains an operational gate** before the first 14-day publication; it has
not run on this implementation branch. A carried product requirement, from ruling
1: the install flow must disclose the default-in posture unmissably.

**Named open rather than resolved:**

6. **Replay exclusion** (§2.6) — no `source` column on `outcome_jobs`.
7. **PR head sha at merge** (§2.1) — not stored.

**Implemented schema and runtime work:**

8. **`outcomes.kind` gains `censored`** — a new *value* on an existing `String(20)`
   column, not a migration.
9. **Migration 007, three tables, live in production:**
   - `reads` gains `files_dropped` and `changed_files` (§5), making
     `partial_read_share` reconstructible from the ledger.
   - **`outcomes` gains `merge_commit_sha`** (§2.3). Without it the numerator has no
     job discriminator and the `N_done = misses + clean + censored` identity can be
     false while every stated rule is obeyed.
   - `outcome_jobs` gains `started_at`, `finished_at`, `error` and
     `claim_generation`, making a crashed Job reclaimable without letting a stale
     holder publish over a newer claim.
10. **`prereg_hash` stored per adjudicated row** in `outcomes.detail` (§12). The
    deploy guard for this v9 lock is built on `m3-60-day-backfill`; its hash is not
    live until the Task 7 deploy.

**Required of `adjudicate.py`:** exactly one classification row per job (§2.3);
**every row writes `installation_id`, `github_repo_id`, `window_days` and
`merge_commit_sha`** — these identity columns are nullable and `store.py:120-122`
records that they are NULL on pre-migration rows, so a row written without them
silently never joins and vanishes from both numerator and denominator; disposition
precedence (§6.2); parsed-instant comparison (§6.1); the sha-retaining variant with
its tie-break (§10); both fixture requirements (§10).

---

## 12. Cadence, venue, and the hash

**RULED (Andrew, 2026-08-07): quarterly — 15 January, 15 April, 15 July, 15
October** — the floor, not a ceiling. Amended the same day: while building buy-in we
may publish **sooner or more often**.

> **The bound is ASYMMETRIC, because the risk is.** v6 bounded all cadence changes
> equally; that was wrong. Publishing more, or earlier, cannot hide a bad number —
> it can only increase disclosure, and no commitment is escaped by honouring it
> twice. Only the shrinking direction threatens the instrument. So:
>
> **Free, needing no amendment at all:**
> - **Tightening the scheduled cadence** (quarterly → monthly, say), prospectively.
>   Safe *because* every scheduled date then ships regardless of what it says — the
>   obligation gets denser, not weaker.
> - **Advancing the first publication date.**
>
> **Allowed, with one condition — off-cycle publications.** An unscheduled
> publication must carry the **full table** (§3): same metric, same denominators,
> the censoring rate, the noise estimates, the undecidable rows. It does not replace
> or reset the next scheduled date.
> **The condition is the whole point.** A discretionary off-cycle publication is the
> one shape in this direction that CAN mislead: choosing to publish an interim
> number *after seeing that it is good* is selective disclosure wearing the costume
> of extra transparency. Requiring the full table makes an off-cycle publication a
> publication rather than a highlight, so the choice of when to publish stops being
> a choice of what to show.
>
> **Bounded, unchanged from v6 — the shrinking direction.** Lengthening the cadence,
> skipping, or postponing is **PROSPECTIVE ONLY**: a new hashed version may change
> future dates; it may **not** move or cancel a date already due. Every prior version
> stays published (§12).
>
> **Worth knowing before publishing more often.** At the merge volumes in
> `design-lock.md:84`, a shorter window mostly produces rows §8 labels *not yet
> decidable* — a count, not a rate. That is not a reason against it: for buy-in, a
> filling scoreboard on a published definition demonstrates the mechanism, which is
> what `product-spec.md:13` says the early product actually is. Just publish them as
> the counts they are, and do not let a run of undecidable rows become a habit of
> publishing only the decidable ones.

⚠ **Venue:** `https://drewjst.github.io/doug/publication/`. Named because §0 promises
a stranger can check us, and a stranger cannot check an unnamed place.

⚠ **Next publication date:** `design-lock.md:61` requires the document carry one and
be public *before* install #1, so a rule keyed to install #1 cannot satisfy it.
**Provisional: 15 January 2027**, superseded by a new hashed version once install #1
dates the real series. A named partial deviation from O3, not a silent omission.

The Doug-on-Doug scoreboard is not on this cadence — it is a live public page (M3).

**A publication ships on its date, good or bad, or the pre-registration is void and
we say so at the venue.** A publication missing either §9 noise estimate is likewise
void. A skipped quarter with no notice is indistinguishable from a hidden bad number.

### The hash

```sh
git rev-parse HEAD
python3 -c "import hashlib,pathlib; print(hashlib.sha256(pathlib.Path('docs/design/outcome-loop/publication-preregistration.md').read_bytes()).hexdigest())"
```

Over the file's bytes as committed, LF newlines, at the named ref — ref and digest
publish together so a stranger can reproduce it.

**Stored per adjudicated row** under key `prereg_hash` in `outcomes.detail`. v1
claimed a receipt "names the definitions in force when its verdict was scored" with
nothing enforcing it; `verdicts.prompt_hash` is a stored column (`store.py:94`)
precisely because that property needs storage. Without it, §12's own rule that a
publication spanning a definition change "names both hashes" is not derivable.

**Amendments are permitted; silent ones are not.** Any change produces a new dated
version and a new hash. **Every prior version stays published.**

---

## 13. What this document does not do

- Does **not** pre-register the derangement positive control. The intent tier stays
  UNBELIEVED until it passes (M6 gated track).
- Does **not** pre-register the PC-track garden probes.
- Does **not** authorise any spend.
- Does **not** license "pattern", "learns", "prevents", or "validated"
  (`product-spec.md:36-50`).
