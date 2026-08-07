"""Adjudication: merged-PR job rows + a revert map → one outcome row each.

This is the core of ROADMAP M3's adjudicator, and deliberately the half with
no moving parts. Everything it needs — the due job rows, the repository's
revert map, the branch the clone actually holds — arrives as an argument, so
the rules that decide a *published* number can be exercised over row fixtures
instead of against a database, a clock and a clone.
`docs/design/outcome-loop/publication-preregistration.md` is the
specification; §2.3, §6.1, §6.2 and §10 are the parts implemented here.

Three properties this module is required to have, and where each is enforced
rather than merely asserted:

* **Purity.** No clock, no network, no ledger. `test_adjudicate.py` pins
  every name this module's own `import` statements bind — module *and*
  symbol *and* alias — and the absence of a clock read, because a lazily
  added `datetime.now()` would be invisible to every fixture-driven test
  below it — each one supplies its own timestamps and would keep passing.
* **Exactly one result per job** (§2.3). `adjudicate` walks `jobs` once and
  appends exactly one entry per job: an `Outcome` where it could classify the
  row, an `Unadjudicable` where it could not. No path emits two and none
  drops one, so the published identity `N_done = misses + clean + censored`
  is true *because of* that rule, not independently of it. An `Unadjudicable`
  job is §6.2's `failed` *status*, which is not a disposition and is not in
  `N_done` — what it must never become is a silent `clean`.
* **Identity travels on every row** (§11). `outcomes.installation_id`,
  `github_repo_id` and `window_days` are nullable columns (`store.py:120-122`
  records that pre-migration rows are NULL), so a row written without them
  joins nothing and vanishes from numerator and denominator alike. `Outcome`
  makes them required, so a missing one raises at construction instead of
  disappearing at publication time.

Not here, on purpose: the Cloud Run Job that claims the rows, the treeless
clone, the write to `outcomes`, and the receipt. Three `outcomes` columns are
also absent because this function cannot know them, and all three are
`nullable=False` with no server default, so the writer has to supply each one:
`observed_at` is the writer's clock, `repo` is not a column on `outcome_jobs`
at all, and `source` (`store.py:119`) names the pipeline that produced the row
rather than anything about the row itself.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, NamedTuple

from pydantic import BaseModel

from .backtest.git_labels import TOLERANCE_DAYS, Commit, commit_instant


class OutcomeKind(StrEnum):
    """The three dispositions, and the whole set of them (§2.3, §6.2).

    `outcomes.kind` also permits `hotfix` (`store.py:117`). It is absent here
    on purpose and not by omission: §10 rules that a hotfix is not a miss and
    that no detector in this codebase can tell "hotfix repairing this PR"
    apart from "hotfix that merely followed it", so the adjudicator must
    never write one. Leaving the value out of the enum makes that a fact
    about the type rather than a line in a docstring.
    """

    REVERT = "revert"
    CLEAN = "clean"
    CENSORED = "censored"


class CensorReason(StrEnum):
    """Why a job left the risk set — the two disjuncts of §6.2's rule 2."""

    # The PR merged somewhere the clone cannot see. `clone_treeless` is
    # `--single-branch` (git_labels.py:97), so a revert on `release-2.4`
    # never enters `git log --all` and its absence is blindness, not survival.
    BASE_REF = "base_ref"
    # No clone at all: uninstalled, deleted, permanently 404. NOT a transient
    # clone failure — §6.2 sends those back to the queue as `failed`.
    UNREACHABLE = "unreachable"


class OutcomeDetail(BaseModel):
    """The evidence behind one disposition — never the judgment (design-lock.md:15).

    `revert_sha` is populated whenever the detector attributed a revert to
    the PR at all, including when that revert fell *outside* the window and
    the row is therefore `clean` or `censored`. Which side it fell on is what
    the two recorded bounds are for, and no redundant flag is needed to say
    it: on a `revert` row the instant satisfies §6.1 by construction, on a
    revert that came too late it sits past `window_ends_at`, and on a label
    §6.1's lower bound rejected it sits before `window_starts_at`. Three
    cases, told apart by the same comparison the publication query runs.
    Keeping the near-miss is what lets §9's hand audit see a 14-day `clean`
    that the 60-day row will call a miss, instead of having to re-derive it.
    """

    # The merge commit this row adjudicates — `outcome_jobs.merge_commit_sha`,
    # carried into `detail` so a receipt names both ends of the pair.
    anchor_sha: str
    revert_sha: str | None = None
    revert_instant: datetime | None = None
    # §6.1's two sides, recorded so an auditor can check the comparison
    # instead of recomputing it from a window length, a merge time and a
    # tolerance. Together with a non-null `revert_instant` they make §6.1's
    # three clean cases readable straight off the row — nothing attributed,
    # attributed but past `window_ends_at`, attributed but before
    # `window_starts_at` — and §6.1 requires the last be distinguishable from
    # the other two, since only it was dropped by the bound.
    window_starts_at: datetime
    window_ends_at: datetime
    base_ref: str
    default_branch: str | None = None
    censor_reason: CensorReason | None = None


class Outcome(BaseModel):
    """One classification row, ready for `outcomes` minus the writer's own facts.

    Every identity field is required. §11: these columns are nullable in the
    schema, and a row that reaches the ledger without them silently never
    joins `outcome_jobs` — it disappears from the numerator and the
    denominator at once, which is the one failure mode a published miss rate
    cannot survive quietly.
    """

    installation_id: int
    github_repo_id: int
    pr_number: int
    window_days: int
    merge_commit_sha: str
    kind: OutcomeKind
    detail: OutcomeDetail


class Unadjudicable(NamedTuple):
    """A job the adjudicator could not classify, and the reason (§6.2).

    Not a disposition and not an `outcomes` row. §6.2 keeps `outcomes.kind`
    and `outcome_jobs.status` as separate vocabularies, and a job the
    adjudicator errored on never entered the precedence chain at all: the
    caller retries it to the attempt ceiling and lands it `failed`, counted
    and published outside `N_done`. The one thing it must never do is fall
    through to `clean`, which would publish a survival nothing established.

    The whole job row travels rather than a key, so the caller can find the
    row again without this module having to know which of its columns the
    queue identifies it by.
    """

    job: Mapping[str, Any]
    reason: str


class Adjudication(NamedTuple):
    """One batch's results: the rows to write, the jobs to fail, and one count.

    Two lists rather than an exception because the batch is one Cloud Run Job
    over one repository's due rows. A single commit whose `%cI` git wrote with
    a UTC offset outside ±24h is unparseable (`git_labels.commit_instant`),
    and raising out of the batch would take every unrelated job in that
    scheduled run down with it.
    """

    outcomes: list[Outcome]
    unadjudicable: list[Unadjudicable]

    @property
    def predated_reverts(self) -> dict[int, int]:
        """Per `window_days`, how many attributed reverts §6.1's bound refused.

        §6.1 adopts that bound knowing it can only *lower* a published miss
        rate — it removes misses from the numerator — and pays for that by
        requiring the count travel with the rate rather than be absorbed into
        the survivals.

        KEYED BY WINDOW, not a single integer, because the rate it has to sit
        beside is not a single integer either: §1 fixes the published unit at
        `(repo, window)` and forbids a pooled rate outright. One merge is
        enqueued at both 14 and 60 days (§6.3), so a flat tally counts one
        dropped label twice and belongs to neither published row. One call
        covers one repository (see `adjudicate`), so keying on `window_days`
        yields exactly `(repo, window)`.

        Derived from the rows instead of tallied beside them: a counter can
        drift from the ledger it claims to describe, and this is the same
        comparison a publication runs over `outcomes.detail`, so the number
        Doug reports and the number a stranger recomputes cannot disagree.
        """
        dropped: dict[int, int] = {}
        for outcome in self.outcomes:
            if (
                outcome.detail.revert_instant is not None
                and outcome.detail.revert_instant < outcome.detail.window_starts_at
            ):
                dropped[outcome.window_days] = dropped.get(outcome.window_days, 0) + 1
        return dropped


def adjudicate(
    jobs: Iterable[Mapping[str, Any]],
    revert_map: Mapping[int, Commit],
    *,
    default_branch: str | None,
) -> Adjudication:
    """Classify every job row, in the order given.

    Returns exactly one entry per job across the two lists (§2.3): an
    `Outcome` for every job classified, an `Unadjudicable` for every job whose
    attributed revert carries a committer date `commit_instant` cannot parse.
    That is the only failure caught here, and it is caught per job rather than
    per batch; everything else — a missing column, a row that cannot build an
    `Outcome` — is a structural error and still raises.

    `jobs` are `outcome_jobs` rows (anything mapping the column names —
    a SQLAlchemy `RowMapping` or a plain dict). `revert_map` is
    `git_labels.parse_revert_targets_evidenced` over the repository's history:
    PR number → the reverting commit that won attribution.

    `default_branch` is the branch the *clone* holds, which is what decides
    censoring — `base_ref` naming a branch the clone never fetched is
    blindness. **`None` means the repository was permanently unreachable**,
    so there is no clone, no default branch and (normally) no revert map
    either. This function cannot tell a permanent 404 from a transient clone
    failure and does not try: §6.2 requires the caller to retry to the
    attempt ceiling and land the job `failed` rather than censoring it, so
    passing `None` is an assertion the caller has to have earned.

    All three of `jobs`, `revert_map` and `default_branch` describe ONE
    repository. A batch spanning repositories would need a revert map and a
    default branch per repository, and the clone is per-repository anyway.
    """
    outcomes: list[Outcome] = []
    unadjudicable: list[Unadjudicable] = []
    for job in jobs:
        revert = revert_map.get(job["pr_number"])
        try:
            # The one step whose input is a string git wrote, so the one step
            # a corpus can make fail. Kept out of `_classify` so the `except`
            # covers the parse and nothing else — pydantic's `ValidationError`
            # is a `ValueError` too, and swallowing that here would turn §11's
            # missing-identity guard into a quietly skipped row.
            revert_instant = commit_instant(revert.date) if revert is not None else None
        except ValueError as exc:
            unadjudicable.append(Unadjudicable(job=job, reason=str(exc)))
            continue
        outcomes.append(_classify(job, revert, revert_instant, default_branch))
    return Adjudication(outcomes, unadjudicable)


def _classify(
    job: Mapping[str, Any],
    revert: Commit | None,
    revert_instant: datetime | None,
    default_branch: str | None,
) -> Outcome:
    """One job row → its disposition, by §6.2's precedence.

    Precedence is 1 → 2 → 3 and it is total: `base_ref` either is the cloned
    default branch or is not, so `censored` and `clean` partition, and
    attribution resolves the single overlap between them.
    """
    merged_at = _as_utc(job["merged_at"])
    # From merged_at and window_days rather than the stored `due_at`, which is
    # equal today (store.enqueue_outcome_job computes it exactly this way) but
    # belongs to the drain: it decides when a job becomes claimable, and §6.1
    # states the window on the two facts a publication defines it from.
    window_ends_at = merged_at + timedelta(days=job["window_days"])
    # §6.1's lower bound, and it is not a formality. `pr_titles_from_subjects`
    # is newest-wins, so a revert of an OLDER PR whose squash title was reused
    # — a dependency bump, "Fix typo" — is attributed to a newer one and
    # arrives dated before the merge it supposedly reverts. That is 6/67 of
    # the labels on sentry and 6/54 on grafana, the two corpora that validated
    # this detector (`scripts/label_precision_delta.py`), and without this
    # bound every one of them publishes as a miss for a PR it predates.
    window_starts_at = merged_at - timedelta(days=TOLERANCE_DAYS)

    censor_reason: CensorReason | None = None
    # Attribution FIRST, ahead of censoring, per §6.2. A PR merged to
    # release-2.4 whose revert was cherry-picked onto the default branch
    # matches both rules — attribution reads only the revert commit's subject
    # and body (git_labels.py:301-316) and never checks where the original
    # landed.
    # Checking base_ref first would take a revert we demonstrably *saw* out of
    # the risk set and lower the published rate, which is the flattering
    # direction and the reason the precedence is written down at all.
    #
    # `<=` is §6.1's inclusive boundary on BOTH sides: a revert landing
    # exactly one window after the merge is inside the window, and so is one
    # landing exactly `TOLERANCE_DAYS` before it.
    #
    # Inclusivity on the LOWER side is what keeps this equal to the label
    # filter the backtest actually runs, which is integer-day and spelled
    # `(revert - merged).days >= -TOLERANCE_DAYS` in `screen_features.py` and
    # `rf_kamei.py` (`label_precision_delta.py` writes the same test inverted,
    # as a drop). `timedelta.days` floors toward -inf, and `floor(x) >= -T`
    # agrees with `x >= -T` ONLY BECAUSE `T` IS AN INTEGER — at a fractional
    # tolerance a -0.2-day lag would be kept here and dropped there. Sharing
    # one constant (design-lock.md:29) makes the two sides read the same
    # NUMBER; it does not by itself make them the same PREDICATE, and
    # test_the_live_bound_and_the_backtest_filter_agree_across_the_boundary
    # is what pins that they are.
    if revert_instant is not None and window_starts_at <= revert_instant <= window_ends_at:
        kind = OutcomeKind.REVERT
    elif default_branch is None:
        kind = OutcomeKind.CENSORED
        censor_reason = CensorReason.UNREACHABLE
    elif job["base_ref"] != default_branch:
        kind = OutcomeKind.CENSORED
        censor_reason = CensorReason.BASE_REF
    else:
        kind = OutcomeKind.CLEAN

    return Outcome(
        installation_id=job["installation_id"],
        github_repo_id=job["github_repo_id"],
        pr_number=job["pr_number"],
        window_days=job["window_days"],
        merge_commit_sha=job["merge_commit_sha"],
        kind=kind,
        detail=OutcomeDetail(
            anchor_sha=job["merge_commit_sha"],
            revert_sha=revert.sha if revert is not None else None,
            revert_instant=revert_instant,
            window_starts_at=window_starts_at,
            window_ends_at=window_ends_at,
            base_ref=job["base_ref"],
            default_branch=default_branch,
            censor_reason=censor_reason,
        ),
    )


def _as_utc(value: datetime) -> datetime:
    """Normalise a job row's timestamp to an aware UTC instant.

    `merged_at` is written aware (`api._payload_timestamp`) into a
    `DateTime(timezone=True)` column, and Postgres hands back the offset it
    declared. sqlite — the test path, and the dialect every test in this
    project runs on — drops it and returns the same instant naive, so a
    fixture built from a round-tripped row would raise on the very comparison
    §6.1 requires. Everything written to that column is UTC, so reattaching
    the zone reads the row rather than guessing at it. Same convention and
    same reason as `ingest._as_utc`.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
