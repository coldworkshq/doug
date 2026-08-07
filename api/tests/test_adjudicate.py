"""The adjudicator core, over row fixtures.

`publication-preregistration.md` §10 does not take effect until the two tests
it names by name are green, so both are here and both are named after it:
`test_the_earlier_instant_wins_when_string_order_disagrees` (a committed
fixture whose UTC offsets make string order and instant order disagree) and
`test_live_labels_equal_backtest_labels_on_the_detector_cases` (the
`git_labels` cases run through the live path).
"""

import ast
import re
from datetime import UTC, datetime, timedelta
from itertools import permutations
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from doug import adjudicate as adjudicate_module
from doug.adjudicate import (
    CensorReason,
    Outcome,
    OutcomeDetail,
    OutcomeKind,
    adjudicate,
)
from doug.backtest.git_labels import (
    TOLERANCE_DAYS,
    Commit,
    commit_instant,
    parse_revert_targets_dated,
    parse_revert_targets_evidenced,
)

_MERGED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _job(pr_number: int, **over: Any) -> dict[str, Any]:
    """One `outcome_jobs` row, carrying every column store.py writes.

    The unread columns (`id`, `due_at`, `status`, `attempts`, `created_at`)
    are here on purpose: a fixture holding only the fields the code happens
    to read cannot notice the day it starts reading another one.
    """
    job: dict[str, Any] = {
        "id": 1000 + pr_number,
        "installation_id": 150424894,
        "github_repo_id": 987654,
        "pr_number": pr_number,
        "merge_commit_sha": f"{pr_number:040d}",
        "merged_at": _MERGED_AT,
        "base_ref": "main",
        "window_days": 14,
        "due_at": _MERGED_AT + timedelta(days=14),
        "status": "running",
        "attempts": 1,
        "created_at": _MERGED_AT,
    }
    return job | over


def _kinds(outcomes: list[Outcome]) -> dict[int, OutcomeKind]:
    return {o.pr_number: o.kind for o in outcomes}


# --- §10 fixture 1: offsets that make string order disagree with instant order


# Two reverts of PR #100. §10's rule is a TWO-LEVEL order — earlier instant
# wins, sha decides only a tie — so this fixture has to make all three
# candidate orderings disagree, because each one on its own is a rule somebody
# could have implemented:
#
#   raw %cI string:  "2026-03-01T02:00:00-05:00" < "2026-03-01T09:00:00+09:00"
#                    → new york wins.  The pre-amendment rule (§6.1).
#   UTC instant:      2026-03-01T00:00:00Z       <  2026-03-01T07:00:00Z
#                    → tokyo wins.     The rule §6.1 declares, and the answer.
#   sha:             "aaa…" < "bbb…"
#                    → new york wins.  §10's tie-break, which must never be
#                                      consulted while the instants differ.
#
# So the +09:00 commit is the earlier event, the later string, and the larger
# sha — only the two-level order picks it. REVIEWING.md:119 is the reason all
# three matter: a property whose every input shares the code's own assumption
# survives every mutant. Both single-dimension corpora were measured, not
# guessed. A single-offset corpus passes with the §6.1 amendment reverted; and
# with sha order *agreeing* with instant order (tokyo "a", new york "b", as
# this fixture was originally written) the whole suite — 735 tests — passed
# against a detector keyed `(sha, instant)` instead of `(instant, sha)`.
_TOKYO_REVERT = Commit(
    sha="b" * 40,  # the LARGER sha, so sha order cannot stand in for the answer
    date="2026-03-01T09:00:00+09:00",  # 2026-03-01T00:00:00Z — the earlier instant
    subject='Revert "Add caching (#100)" (#101)',
)
_NEW_YORK_REVERT = Commit(
    sha="a" * 40,  # the smaller sha, and the wrong answer
    date="2026-03-01T02:00:00-05:00",  # 2026-03-01T07:00:00Z — the later instant
    subject='Revert "Add caching (#100)" (#102)',
)
# `git log` is newest-first, so the later instant leads.
_OFFSET_CORPUS = [
    _NEW_YORK_REVERT,
    _TOKYO_REVERT,
    Commit(sha="c" * 40, date="2026-02-01T00:00:00+00:00", subject="Add caching (#100)"),
]


def test_the_earlier_instant_wins_when_string_order_disagrees():
    evidenced = parse_revert_targets_evidenced(_OFFSET_CORPUS, {})

    assert evidenced[100] == _TOKYO_REVERT
    # And the string rule really does disagree here — otherwise the assertion
    # above would hold for a detector that never parsed anything.
    assert parse_revert_targets_dated(_OFFSET_CORPUS, {}) == {100: _NEW_YORK_REVERT.date}


def test_a_disposition_follows_the_earlier_instant_not_the_earlier_string():
    # The window closes at 2026-03-01T03:00:00Z, which falls between the two
    # reverts' instants: the earlier instant (00:00Z) is inside it, the later
    # (07:00Z) is outside. A detector picking by string order hands the
    # adjudicator the 07:00Z commit and this merge publishes as a survival.
    job = _job(100, merged_at=datetime(2026, 2, 15, 3, tzinfo=UTC))

    revert_map = parse_revert_targets_evidenced(_OFFSET_CORPUS, {})

    [outcome], _ = adjudicate([job], revert_map, default_branch="main")

    assert outcome.kind is OutcomeKind.REVERT
    assert outcome.detail.revert_sha == _TOKYO_REVERT.sha
    assert outcome.detail.revert_instant == datetime(2026, 3, 1, tzinfo=UTC)


def test_a_tie_on_the_instant_breaks_to_the_smallest_sha():
    # `utc` and `berlin` are one instant spelled two ways, so nothing but the
    # sha can separate them — §10 rules it is the smaller, because that sha is
    # the artifact a customer checks by hand.
    #
    # `late` is what stops the assertion from also passing under a rule that
    # reads the sha FIRST: it holds the smallest sha in the corpus and a
    # strictly later instant, so sha-primary picks it and the two-level order
    # does not. Without it this test is blind in exactly the direction the
    # offset fixture above was.
    utc = Commit(sha="b" * 40, date="2026-03-01T00:00:00+00:00", subject="Revert #200")
    berlin = Commit(sha="a" * 40, date="2026-03-01T01:00:00+01:00", subject="Revert #200")
    late = Commit(sha="0" * 40, date="2026-03-01T05:00:00+00:00", subject="Revert #200")

    # `git log`'s emission order decides which commit is the incumbent, and it
    # must not decide the winner — so every arrival order has to agree.
    for corpus in permutations([utc, berlin, late]):
        assert parse_revert_targets_evidenced(list(corpus), {})[200] == berlin


def test_a_commit_date_without_an_offset_is_refused_rather_than_guessed():
    # `astimezone` on a naive datetime silently reads it as local time; a
    # revert instant wrong by hours moves a label across a window boundary.
    with pytest.raises(ValueError):
        parse_revert_targets_evidenced(
            [
                Commit(sha="1" * 40, date="2026-03-01T00:00:00", subject="Revert #5"),
                Commit(sha="2" * 40, date="2026-03-02T00:00:00", subject="Revert #5"),
            ],
            {},
        )


# A committer date git itself writes and `datetime.fromisoformat` refuses.
# git stores whatever UTC offset the committing environment declared and
# prints it back verbatim, so `GIT_COMMITTER_DATE="@1772000000 +2400"` reaches
# `%cI` as this, while `fromisoformat` accepts only offsets inside ±24h.
# Reproduced against git and CPython before this test was written.
_OUT_OF_RANGE_OFFSET = "2026-02-26T06:13:20+24:00"


def test_an_out_of_range_utc_offset_is_refused_and_names_the_date_it_refused():
    # `fromisoformat`'s own message names the offset it rejected and never the
    # string, so the raise is rewrapped: the string is what leads back to the
    # commit, and a reason that cannot be traced to a commit is not visible.
    with pytest.raises(ValueError) as refused:
        commit_instant(_OUT_OF_RANGE_OFFSET)

    assert _OUT_OF_RANGE_OFFSET in str(refused.value)


def test_an_unparseable_commit_date_fails_its_own_jobs_and_not_the_batch():
    # One commit in a repository's history must not abort a whole scheduled
    # run: the drain claims every due row for the repo at once, and the other
    # jobs have nothing to do with this commit.
    revert_map = {
        800: Commit(sha="a" * 40, date=_OUT_OF_RANGE_OFFSET, subject="Revert #800"),
        801: Commit(sha="b" * 40, date=_REVERT_DATE, subject="Revert #801"),
    }
    jobs = [_job(800), _job(801), _job(802)]

    result = adjudicate(jobs, revert_map, default_branch="main")

    # The jobs that do not depend on the bad commit are adjudicated normally…
    assert _kinds(result.outcomes) == {801: OutcomeKind.REVERT, 802: OutcomeKind.CLEAN}
    # …and the one that does is reported, not swallowed and not made `clean`.
    assert [u.job["pr_number"] for u in result.unadjudicable] == [800]
    assert _OUT_OF_RANGE_OFFSET in result.unadjudicable[0].reason
    assert 800 not in _kinds(result.outcomes)


def test_every_job_lands_in_exactly_one_of_the_two_result_lists():
    # §2.3's one-row rule survives the split: `N_done` counts the outcomes,
    # §6.2's `failed` counts the rest, and neither list can drop a job.
    revert_map = {
        810: Commit(sha="a" * 40, date=_OUT_OF_RANGE_OFFSET, subject="Revert #810"),
        811: Commit(sha="b" * 40, date=_OUT_OF_RANGE_OFFSET, subject="Revert #811"),
    }
    jobs = [_job(810), _job(811), _job(812), _job(813, base_ref="release-2.4")]

    result = adjudicate(jobs, revert_map, default_branch="main")

    assert [o.pr_number for o in result.outcomes] == [812, 813]
    assert [u.job["pr_number"] for u in result.unadjudicable] == [810, 811]
    assert len(result.outcomes) + len(result.unadjudicable) == len(jobs)


def test_a_row_that_cannot_build_an_outcome_still_raises_rather_than_failing_one_job():
    # The per-job catch is scoped to the date parse on purpose: pydantic's
    # ValidationError IS a ValueError, so an `except ValueError` around the
    # whole classification would turn §11's identity guard from a loud failure
    # into a job quietly listed as unadjudicable — which is the same
    # disappearing act §11 exists to prevent, one layer further out.
    job = _job(820, installation_id="not-an-installation")

    with pytest.raises(ValidationError):
        adjudicate([job], {}, default_branch="main")


# --- §10 fixture 2: live label ≡ backtest label ----------------------------

_MERGE_DATE = "2026-01-01T00:00:00+00:00"
_REVERT_DATE = "2026-01-10T00:00:00+00:00"

# The detector cases §10 names, plus the two ordinary attribution paths, each
# with the PRs it must label and the PRs it must leave alone.
_DETECTOR_CASES: list[tuple[str, list[Commit], set[int], set[int]]] = [
    (
        "nested #N inside the quoted title",
        [
            Commit(sha="1" * 40, date=_REVERT_DATE, subject='Revert "Add caching (#100)" (#101)'),
            Commit(sha="2" * 40, date=_MERGE_DATE, subject="Add caching (#100)"),
            Commit(sha="3" * 40, date=_MERGE_DATE, subject="Ship metrics (#102)"),
        ],
        {100},
        {102},
    ),
    (
        "body sha, quoted title that does not reproduce the PR title",
        [
            Commit(
                sha="4" * 40,
                date=_REVERT_DATE,
                subject='Revert "Wire up config metrics correctly"',
                body="This reverts commit " + "5" * 40 + ".",
            ),
            Commit(sha="5" * 40, date=_MERGE_DATE, subject="Wire up config metrics (#77)"),
            Commit(sha="6" * 40, date=_MERGE_DATE, subject="Add docs (#78)"),
        ],
        {77},
        {78},
    ),
    (
        "ambiguous short sha resolves to nothing",
        [
            Commit(
                sha="7" * 40,
                date=_REVERT_DATE,
                subject='Revert "Thing"',
                body="This reverts commit " + "f" * 7 + ".",
            ),
            Commit(sha="f" * 7 + "1" * 33, date=_MERGE_DATE, subject="A (#1)"),
            Commit(sha="f" * 7 + "2" * 33, date=_MERGE_DATE, subject="B (#2)"),
        ],
        set(),
        {1, 2},
    ),
    (
        '"Reland" carries the body marker and is the opposite of a revert',
        [
            Commit(
                sha="8" * 40,
                date=_REVERT_DATE,
                subject="Reland: Add caching",
                body="This reverts commit " + "9" * 40 + ".",
            ),
            Commit(sha="9" * 40, date=_MERGE_DATE, subject="Revert caching (#9)"),
            Commit(sha="a" * 40, date=_MERGE_DATE, subject="Add caching (#10)"),
        ],
        set(),
        {9, 10},
    ),
    (
        "quoted title via the squash-title map, and the bare #N form",
        [
            Commit(sha="b" * 40, date=_REVERT_DATE, subject='Revert "Add rate limiter" (#44)'),
            Commit(sha="c" * 40, date=_REVERT_DATE, subject="Revert #7, broke prod"),
            Commit(sha="d" * 40, date=_MERGE_DATE, subject="Add rate limiter (#40)"),
            Commit(sha="e" * 40, date=_MERGE_DATE, subject="Old thing (#7)"),
            Commit(sha="0" * 40, date=_MERGE_DATE, subject="Unrelated (#50)"),
        ],
        {40, 7},
        {50},
    ),
]


@pytest.mark.parametrize(
    "commits,reverted,surviving",
    [case[1:] for case in _DETECTOR_CASES],
    ids=[case[0] for case in _DETECTOR_CASES],
)
def test_live_labels_equal_backtest_labels_on_the_detector_cases(commits, reverted, surviving):
    """§10's "same detector both sides", run end to end through the live path.

    Attribution is asserted three ways over one corpus: what the backtest
    computes, what the sha-retaining variant computes, and what a published
    `outcomes.kind` ends up being. If the live path ever stops agreeing with
    the backtest, the published rate stops being comparable to the validated
    evidence it will be quoted beside.
    """
    dated = parse_revert_targets_dated(commits)
    evidenced = parse_revert_targets_evidenced(commits)

    assert set(dated) == reverted
    assert set(evidenced) == reverted
    # Same dates too. That claim is only tested here for single-offset
    # corpora, which is what a real `git log` mostly is and what the cached
    # backtest corpora are; where offsets differ the two deliberately part
    # company, and test_the_earlier_instant_wins_when_string_order_disagrees
    # is where that divergence is pinned.
    assert {number: c.date for number, c in evidenced.items()} == dated

    jobs = [_job(number) for number in sorted(reverted | surviving)]
    outcomes, _ = adjudicate(jobs, evidenced, default_branch="main")

    assert _kinds(outcomes) == {
        **{number: OutcomeKind.REVERT for number in reverted},
        **{number: OutcomeKind.CLEAN for number in surviving},
    }
    # The sha promised to the receipt (product-spec.md:39) is the reverting
    # commit's, not the anchor's.
    for outcome in outcomes:
        if outcome.kind is OutcomeKind.REVERT:
            assert outcome.detail.revert_sha == evidenced[outcome.pr_number].sha
            assert outcome.detail.anchor_sha == outcome.merge_commit_sha


# --- §6.2 precedence -------------------------------------------------------


def _revert_map(pr_number: int, date: str = _REVERT_DATE) -> dict[int, Commit]:
    return {pr_number: Commit(sha="d" * 40, date=date, subject=f"Revert #{pr_number}")}


def test_an_attributed_revert_on_a_release_branch_is_a_revert_not_a_censor():
    # The single overlap §6.2 exists to arbitrate: merged to release-2.4, and
    # the revert was cherry-picked onto the default branch where the clone can
    # see it. Censoring first would take a miss we demonstrably observed out
    # of the risk set and lower the published rate.
    job = _job(300, base_ref="release-2.4")

    [outcome], _ = adjudicate([job], _revert_map(300), default_branch="main")

    assert outcome.kind is OutcomeKind.REVERT
    assert outcome.detail.censor_reason is None


def test_an_attributed_revert_beats_an_unreachable_repository_too():
    job = _job(301)

    [outcome], _ = adjudicate([job], _revert_map(301), default_branch=None)

    assert outcome.kind is OutcomeKind.REVERT


def test_a_non_default_base_ref_with_no_revert_is_censored_never_clean():
    job = _job(302, base_ref="release-2.4")

    [outcome], _ = adjudicate([job], {}, default_branch="main")

    assert outcome.kind is OutcomeKind.CENSORED
    assert outcome.detail.censor_reason is CensorReason.BASE_REF


def test_a_permanently_unreachable_repository_is_censored():
    job = _job(303)

    [outcome], _ = adjudicate([job], {}, default_branch=None)

    assert outcome.kind is OutcomeKind.CENSORED
    assert outcome.detail.censor_reason is CensorReason.UNREACHABLE


def test_the_default_branch_is_the_clones_not_the_string_main():
    # A repo whose default branch is `trunk` must not censor its own merges,
    # and must censor the ones that went to `main`.
    [on_trunk], _ = adjudicate([_job(304, base_ref="trunk")], {}, default_branch="trunk")
    [on_main], _ = adjudicate([_job(305, base_ref="main")], {}, default_branch="trunk")

    assert on_trunk.kind is OutcomeKind.CLEAN
    assert on_main.kind is OutcomeKind.CENSORED


def test_hotfix_is_not_a_disposition_the_adjudicator_can_reach():
    # §2.3/§10: `outcomes.kind` permits `hotfix` (store.py:117) and the
    # adjudicator must never write one — no detector here can tell a hotfix
    # repairing this PR from a hotfix that merely followed it.
    assert {kind.value for kind in OutcomeKind} == {"revert", "clean", "censored"}


# --- §6.1 the window predicate ---------------------------------------------


def test_a_revert_exactly_at_the_windows_upper_boundary_is_inside_it():
    job = _job(400)
    boundary = (_MERGED_AT + timedelta(days=14)).isoformat()

    [outcome], _ = adjudicate([job], _revert_map(400, boundary), default_branch="main")

    assert outcome.kind is OutcomeKind.REVERT


def test_a_revert_one_second_past_the_upper_boundary_is_outside_it():
    job = _job(401)
    past = (_MERGED_AT + timedelta(days=14, seconds=1)).isoformat()

    [outcome], _ = adjudicate([job], _revert_map(401, past), default_branch="main")

    assert outcome.kind is OutcomeKind.CLEAN
    # The near-miss is still evidence and is still recorded — a 14-day `clean`
    # whose 60-day row will be a miss should not need re-deriving by hand.
    assert outcome.detail.revert_sha == "d" * 40


def test_the_window_is_measured_from_merged_at_and_window_days_not_from_due_at():
    # `due_at` belongs to the drain: it decides when a job becomes claimable.
    # §6.1 states the window on merged_at and window_days, so a due_at that
    # disagrees must not move a label.
    job = _job(402, due_at=_MERGED_AT + timedelta(days=365))
    past = (_MERGED_AT + timedelta(days=20)).isoformat()

    [outcome], _ = adjudicate([job], _revert_map(402, past), default_branch="main")

    assert outcome.kind is OutcomeKind.CLEAN
    assert outcome.detail.window_ends_at == _MERGED_AT + timedelta(days=14)


def test_a_naive_merged_at_is_read_as_utc_rather_than_raising():
    # Every test in this project runs sqlite, which drops the offset a
    # DateTime(timezone=True) column declares and hands the instant back
    # naive. Comparing that against an aware revert instant is a TypeError.
    job = _job(403, merged_at=_MERGED_AT.replace(tzinfo=None))
    boundary = (_MERGED_AT + timedelta(days=14)).isoformat()

    [outcome], _ = adjudicate([job], _revert_map(403, boundary), default_branch="main")

    assert outcome.kind is OutcomeKind.REVERT


def test_the_same_merge_at_two_windows_can_disagree():
    # 14 and 60 are independent rows with independent denominators (§6.3), and
    # a revert on day 30 is a survival at 14 days and a miss at 60.
    day_30 = (_MERGED_AT + timedelta(days=30)).isoformat()
    jobs = [_job(404), _job(404, window_days=60, due_at=_MERGED_AT + timedelta(days=60))]

    outcomes, _ = adjudicate(jobs, _revert_map(404, day_30), default_branch="main")

    assert [o.kind for o in outcomes] == [OutcomeKind.CLEAN, OutcomeKind.REVERT]
    assert [o.window_days for o in outcomes] == [14, 60]


# --- §6.1 the window's LOWER bound -----------------------------------------
#
# The offsets below are written as literal days rather than built from
# `TOLERANCE_DAYS`, and that is the point of them. A fixture placed at
# `merged_at - timedelta(days=TOLERANCE_DAYS)` moves whenever the constant
# moves, so it asserts "the code agrees with itself" and survives every value
# the constant could take — REVIEWING.md:119's failure exactly. Ruled at 1 day
# (§6.1), so 1 day is what the tests say.
#
# `_PREDATED` is 3 days before the merge, inside the 14-day window's *width*,
# because a lower bound written `merged_at - timedelta(days=window_days)` — a
# symmetric window, the obvious wrong shape — would still call it a miss.
_PREDATED = (_MERGED_AT - timedelta(days=3)).isoformat()
_LOWER_BOUNDARY = (_MERGED_AT - timedelta(days=1)).isoformat()
_JUST_BELOW = (_MERGED_AT - timedelta(days=1, seconds=1)).isoformat()
_SAME_DAY_SKEW = (_MERGED_AT - timedelta(hours=6)).isoformat()


def test_a_revert_dated_days_before_the_merge_is_not_a_miss():
    # A revert cannot land before the PR it reverts. These labels exist anyway
    # — 6/67 on sentry, 6/54 on grafana — because `pr_titles_from_subjects` is
    # newest-wins and a reused squash title attributes an older PR's revert to
    # a newer one. Without §6.1's lower bound each one publishes as a miss for
    # a PR it predates.
    job = _job(410)

    [outcome], _ = adjudicate([job], _revert_map(410, _PREDATED), default_branch="main")

    assert outcome.kind is OutcomeKind.CLEAN


def test_a_revert_within_the_tolerance_is_still_a_miss():
    # The reason the bound is not a strict `>= merged_at`: `%cI` is the
    # committer's clock and `merged_at` is GitHub's, so a same-day revert can
    # be stamped hours before the merge it undoes. Dropping those would throw
    # away real misses — and would diverge from the backtest corpora, which is
    # the opposite of the error the bound exists to fix.
    job = _job(411)

    [outcome], _ = adjudicate([job], _revert_map(411, _SAME_DAY_SKEW), default_branch="main")

    assert outcome.kind is OutcomeKind.REVERT


def test_a_revert_exactly_at_the_windows_lower_boundary_is_inside_it():
    # §6.1 is inclusive on the left as well as the right: `merged_at -
    # TOLERANCE_DAYS <= revert_instant`. Inclusive is also what makes this
    # predicate equal to the backtest's `lag_days >= -TOLERANCE_DAYS`, so the
    # direction is not a free choice — the other one drops a label live that
    # the corpora keep.
    job = _job(412)

    [outcome], _ = adjudicate([job], _revert_map(412, _LOWER_BOUNDARY), default_branch="main")

    assert outcome.kind is OutcomeKind.REVERT


def test_a_revert_one_second_below_the_lower_boundary_is_outside_it():
    job = _job(413)

    [outcome], _ = adjudicate([job], _revert_map(413, _JUST_BELOW), default_branch="main")

    assert outcome.kind is OutcomeKind.CLEAN


def test_a_label_the_lower_bound_dropped_is_not_an_ordinary_survival():
    # §6.1 forbids absorbing the drop into the survivals. Three rows that all
    # publish as `clean`, and the recorded bounds are what tell them apart:
    # nothing was ever attributed / a revert came too late / a revert was
    # impossible. A reader who cannot separate the third is reading a rate
    # that quietly shrank.
    late = (_MERGED_AT + timedelta(days=20)).isoformat()
    jobs = [_job(420), _job(421), _job(422)]
    reverts = _revert_map(421, late) | _revert_map(422, _PREDATED)

    result = adjudicate(jobs, reverts, default_branch="main")
    nothing, too_late, impossible = result.outcomes

    assert [o.kind for o in result.outcomes] == [OutcomeKind.CLEAN] * 3
    assert nothing.detail.revert_instant is None
    assert too_late.detail.revert_instant > too_late.detail.window_ends_at
    assert impossible.detail.revert_instant < impossible.detail.window_starts_at
    assert impossible.detail.window_starts_at == _MERGED_AT - timedelta(days=1)


def test_the_count_of_labels_the_lower_bound_dropped_travels_with_the_batch():
    # §6.1 adopts a bound that can only lower a published rate, and pays for
    # it by publishing how many labels it removed. A batch that reports the
    # drop as zero while dropping labels is the absorbed version of exactly
    # the same edit.
    late = (_MERGED_AT + timedelta(days=20)).isoformat()
    jobs = [_job(430), _job(431), _job(432), _job(433, base_ref="release-2.4")]
    reverts = (
        _revert_map(430, _REVERT_DATE)
        | _revert_map(431, late)
        | _revert_map(432, _PREDATED)
        # Censored, so it never reaches the numerator either way — but without
        # the bound §6.2's attribution-first rule makes it a `revert`, so the
        # bound really did drop it and the count says so.
        | _revert_map(433, _PREDATED)
    )

    result = adjudicate(jobs, reverts, default_branch="main")

    assert [o.kind for o in result.outcomes] == [
        OutcomeKind.REVERT,
        OutcomeKind.CLEAN,
        OutcomeKind.CLEAN,
        OutcomeKind.CENSORED,
    ]
    assert result.predated_reverts == {14: 2}


def test_a_batch_that_dropped_nothing_reports_no_drops():
    # The counter has to be able to say zero, or "2" above proves only that it
    # counts rows.
    late = (_MERGED_AT + timedelta(days=20)).isoformat()
    jobs = [_job(440), _job(441), _job(442)]
    reverts = _revert_map(440, _REVERT_DATE) | _revert_map(441, late)

    assert adjudicate(jobs, reverts, default_branch="main").predated_reverts == {}


def test_one_tolerance_constant_is_defined_and_the_scripts_do_not_redefine_it():
    # design-lock.md:29 makes `git_labels` the only detector so that live
    # labels and backtest labels are the same event. A second `TOLERANCE_DAYS`
    # anywhere is that property being false again, and it was false until this
    # ruling: `scripts/screen_features.py` defined its own, `scripts/rf_kamei.py`
    # re-exported it, and `adjudicate.py` had no lower bound at all — three
    # answers to one question.
    api = Path(adjudicate_module.__file__).parents[1]
    definitions = sorted(
        path.relative_to(api).as_posix()
        for path in [*api.glob("doug/**/*.py"), *api.glob("scripts/*.py")]
        if re.search(r"^TOLERANCE_DAYS\s*=", path.read_text(), re.MULTILINE)
    )

    assert definitions == ["doug/backtest/git_labels.py"]
    assert TOLERANCE_DAYS == 1


# --- §2.3 exactly one row per job ------------------------------------------


def test_every_job_gets_exactly_one_row_and_they_stay_in_order():
    # The identity N_done = misses + clean + censored holds *because* of this
    # rule. Two jobs here share a PR number and window and differ only by
    # merge sha — schema-permitted by uq_outcome_job, and the case §2.3 says
    # the numerator's join key must survive.
    jobs = [
        _job(500),
        _job(500, merge_commit_sha="e" * 40),
        _job(501, base_ref="release-2.4"),
        _job(502),
    ]

    outcomes, unadjudicable = adjudicate(jobs, _revert_map(500), default_branch="main")

    assert len(outcomes) == len(jobs)
    assert unadjudicable == []
    assert [o.merge_commit_sha for o in outcomes] == [j["merge_commit_sha"] for j in jobs]
    assert [o.kind for o in outcomes] == [
        OutcomeKind.REVERT,
        OutcomeKind.REVERT,
        OutcomeKind.CENSORED,
        OutcomeKind.CLEAN,
    ]


def test_no_jobs_yields_no_rows():
    assert adjudicate([], _revert_map(1), default_branch="main") == ([], [])


def test_every_row_carries_the_identity_its_publication_join_needs():
    jobs = [_job(600), _job(601, base_ref="release-2.4"), _job(602)]

    outcomes, _ = adjudicate(jobs, _revert_map(600), default_branch="main")

    for outcome, job in zip(outcomes, jobs, strict=True):
        assert outcome.installation_id == job["installation_id"]
        assert outcome.github_repo_id == job["github_repo_id"]
        assert outcome.pr_number == job["pr_number"]
        assert outcome.window_days == job["window_days"]
        assert outcome.merge_commit_sha == job["merge_commit_sha"]


@pytest.mark.parametrize(
    "missing",
    ["installation_id", "github_repo_id", "pr_number", "window_days", "merge_commit_sha"],
)
def test_an_outcome_cannot_be_built_without_a_join_key(missing):
    # §11: these columns are nullable in `outcomes`, so a row written without
    # one joins nothing and vanishes from both numerator and denominator
    # instead of failing loudly. The model is what makes that impossible.
    fields: dict[str, Any] = {
        "installation_id": 1,
        "github_repo_id": 2,
        "pr_number": 3,
        "window_days": 14,
        "merge_commit_sha": "a" * 40,
        "kind": OutcomeKind.CLEAN,
        "detail": OutcomeDetail(
            anchor_sha="a" * 40,
            window_starts_at=_MERGED_AT,
            window_ends_at=_MERGED_AT,
            base_ref="main",
        ),
    }
    del fields[missing]

    with pytest.raises(ValidationError):
        Outcome(**fields)


# --- purity ----------------------------------------------------------------


def test_the_cores_import_statements_bind_exactly_these_names_and_none_dynamically():
    # WHAT THIS PINS: every `import` statement in adjudicate.py as
    # (module, imported name, alias) — the symbol, not only the module it came
    # from. Module names alone are not a purity guard, because an allowlisted
    # module can supply an unwanted name or an unwanted binding:
    #
    #   from datetime import datetime as _wall   → `_wall.now(UTC)`, and the
    #       clock test below monkeypatches `datetime`, not the alias
    #   from .backtest.git_labels import clone_treeless  → shells out to
    #       `git clone`, from a module that is on the list for `Commit`
    #
    # Both passed while only modules were asserted; both fail now, and the
    # second was re-checked by mutation after this test was rewritten.
    # `__import__("time")` is not an import statement at all, hence the second
    # assertion.
    #
    # WHAT IT DOES NOT PIN: the transitive graph. `git_labels` itself shells
    # out to git for callers that clone; the point is which names *this*
    # module can reach directly. `datetime` is on the list because the module
    # needs UTC and timedelta — the clock test below is what stops it being
    # used to read one.
    tree = ast.parse(Path(adjudicate_module.__file__).read_text())
    bound: set[tuple[str, str, str | None]] = set()
    dynamic: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bound.update((alias.name, alias.name, alias.asname) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            bound.update((module, alias.name, alias.asname) for alias in node.names)
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "__import__":
                dynamic.add("__import__")
            elif isinstance(func, ast.Attribute) and func.attr == "import_module":
                dynamic.add("import_module")

    assert bound == {
        ("__future__", "annotations", None),
        ("collections.abc", "Iterable", None),
        ("collections.abc", "Mapping", None),
        ("datetime", "UTC", None),
        ("datetime", "datetime", None),
        ("datetime", "timedelta", None),
        ("enum", "StrEnum", None),
        ("typing", "Any", None),
        ("typing", "NamedTuple", None),
        ("pydantic", "BaseModel", None),
        (".backtest.git_labels", "TOLERANCE_DAYS", None),
        (".backtest.git_labels", "Commit", None),
        (".backtest.git_labels", "commit_instant", None),
    }
    assert dynamic == set()


def test_no_disposition_reads_a_clock(monkeypatch):
    # A regression guard, and deliberately one: nothing in adjudicate.py names
    # `datetime` at runtime today, so this passes trivially now and fails the
    # moment somebody reaches for `datetime.now(UTC)` to decide a disposition.
    # That edit is the one this module cannot survive — every test here
    # supplies its own timestamps, so a clock read would change what gets
    # published without changing a single expectation below it.
    class _NoClock:
        @staticmethod
        def now(*_args, **_kwargs):
            raise AssertionError("adjudicate() read a clock")

        @staticmethod
        def utcnow(*_args, **_kwargs):
            raise AssertionError("adjudicate() read a clock")

        @staticmethod
        def today(*_args, **_kwargs):
            raise AssertionError("adjudicate() read a clock")

    jobs = [_job(700), _job(701, base_ref="release-2.4"), _job(702)]
    revert_map = _revert_map(700)
    expected = adjudicate(jobs, revert_map, default_branch="main")

    monkeypatch.setattr(adjudicate_module, "datetime", _NoClock)

    assert adjudicate(jobs, revert_map, default_branch="main") == expected


def test_the_drop_count_is_keyed_by_window_so_one_label_is_not_counted_twice():
    # §1 fixes the published unit at (repo, window) and forbids a pooled rate.
    # One merge is enqueued at BOTH windows (§6.3), so a flat tally reports 2
    # for a single dropped label and belongs to neither published row. This is
    # the case the original counter got wrong: it summed rows, not labels.
    jobs = [_job(450, window_days=14), _job(450, window_days=60)]
    reverts = _revert_map(450, _PREDATED)

    result = adjudicate(jobs, reverts, default_branch="main")

    assert [o.kind for o in result.outcomes] == [OutcomeKind.CLEAN, OutcomeKind.CLEAN]
    # One label, dropped once in each window's row — not "2" pooled.
    assert result.predated_reverts == {14: 1, 60: 1}


def test_the_live_bound_and_the_backtest_filter_agree_across_the_boundary():
    # §6.1's whole purpose is that live and backtest label the SAME event
    # (design-lock.md:29). Sharing TOLERANCE_DAYS makes both sides read one
    # number; it does not by itself make them one predicate. The backtest
    # filters with integer-day arithmetic — `(revert - merged).days >=
    # -TOLERANCE_DAYS` in screen_features.py and rf_kamei.py — while the
    # adjudicator compares aware instants against a timedelta. `timedelta.days`
    # floors toward -inf, so the two agree only because TOLERANCE_DAYS is an
    # integer. Nothing else in the suite compares the two forms.
    lags = [
        timedelta(days=-TOLERANCE_DAYS),  # exactly the bound
        timedelta(days=-TOLERANCE_DAYS, seconds=-1),  # one second outside
        timedelta(days=-TOLERANCE_DAYS, seconds=1),  # one second inside
        timedelta(days=-TOLERANCE_DAYS, microseconds=-1),
        timedelta(hours=-6),
        timedelta(days=-2),
        timedelta(0),
        timedelta(days=14),
    ]
    for lag in lags:
        revert_at = _MERGED_AT + lag
        live_keeps = (
            _MERGED_AT - timedelta(days=TOLERANCE_DAYS) <= revert_at
        ) and revert_at <= _MERGED_AT + timedelta(days=14)
        backtest_keeps = (revert_at - _MERGED_AT).days >= -TOLERANCE_DAYS and lag <= (
            timedelta(days=14)
        )
        assert live_keeps == backtest_keeps, f"diverged at lag={lag}"

    # And the integrality precondition the agreement rests on.
    assert isinstance(TOLERANCE_DAYS, int)
