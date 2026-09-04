"""The governing-verdict rule — pre-registration §2.1, as SQL'd in §2.2.

These tests guard the one selection rule that BOTH a customer's receipt and
the published quarterly miss rate run. The whole claim of the outcome loop is
that those two numbers come from the same ledger under the same definition,
so a divergence here is not a bug in a helper, it is the product's central
claim failing quietly.

The file grew outward from that rule and now covers all three layers built on
it, in order: `governing_verdict` (the rule itself, differential-tested
against §2.2's own SQL), `receipt()` (the document assembled around it), and
GET /v1/prs/{n}/receipt (the document served, under two token classes). The
last section carries a second concern the first two do not — that no request
can be answered from another installation's ledger rows — and its comment
header says how that is established.
"""

import base64
import itertools
import json
import pathlib
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text

from doug import api, store, tenancy
from doug.api import app
from doug.models import Band

PREREGISTRATION = (
    pathlib.Path(__file__).resolve().parents[2]
    / "docs"
    / "design"
    / "outcome-loop"
    / "publication-preregistration.md"
)

NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
INSTALLATION_ID = 100
REPO_ID = 200
PR_NUMBER = 42
REPO = "drewjst/doug"
WINDOW_DAYS = 14

# Copied verbatim from publication-preregistration.md §2.2's ranking CTE,
# comments included, down to the `governing` step. Only the document's final
# aggregate (`SELECT count(DISTINCT j.pr_number) …`) is replaced, by the
# projection that names the governing rows themselves — that outer query is
# the DENOMINATOR, and the denominator's `g.band = 'cleared'` filter is
# exactly the qualification this selector must NOT apply.
#
# This duplication is deliberate and must not be refactored away. Both sides
# written in SQLAlchemy would let one shared misreading of §2.1 pass green.
# If this string must change to make a test pass, the LOCKED pre-registration
# changed — stop and escalate rather than editing it.
GOVERNING_SQL = """
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
SELECT id FROM governing
"""


def _mutate(*swaps: tuple[str, str]) -> str:
    """Derive a WRONG variant of §2.2's SQL by explicit surgery on the text.

    Every swap must fire. If the locked document is ever amended so that a
    fragment below no longer appears, this raises — rather than quietly
    yielding a "mutant" identical to the original, which would leave
    test_the_agreement_corpus_can_catch_each_wrong_rule green while proving
    nothing at all.
    """
    sql = GOVERNING_SQL
    for old, new in swaps:
        assert old in sql, f"§2.2's SQL no longer contains: {old!r}"
        sql = sql.replace(old, new)
    assert sql != GOVERNING_SQL
    return sql


# Every way this rule can be got wrong, written out as SQL. These are not
# alternatives under consideration — each is a defect the corpus below must be
# able to see. A differential test whose fixtures cannot separate the right
# rule from the wrong ones proves only that two queries agree on easy cases.
WRONG_RULES = {
    # What §2.1's prose alone reads like: "the verdict with the greatest
    # scored_at", with the tier requirement applied to the winner afterwards.
    "tier filtered after ranking": _mutate(
        (
            "SELECT v.installation_id, v.github_repo_id, v.pr_number, v.band, v.id,",
            "SELECT v.installation_id, v.github_repo_id, v.pr_number, v.band, v.tier, v.id,",
        ),
        (
            "  WHERE v.tier = 'reader'\n    AND v.scored_at <= j.merged_at",
            "  WHERE v.scored_at <= j.merged_at",
        ),
        ("SELECT id FROM governing", "SELECT id FROM governing WHERE tier = 'reader'"),
    ),
    # The denominator's qualification hoisted into selection — the mistake that
    # would leave every flagged PR with no receipt.
    "band qualifying the selection": _mutate(
        ("  WHERE v.tier = 'reader'", "  WHERE v.tier = 'reader'\n    AND v.band = 'cleared'"),
    ),
    # §2.6's structural exclusion dropped.
    "installation existence not required": _mutate(
        (
            "    AND EXISTS (\n      SELECT 1 FROM installations i\n"
            "      WHERE i.installation_id = j.installation_id\n    )\n",
            "",
        ),
    ),
    # §2.1's stated tie-break run backwards.
    "ties broken to the lowest id": _mutate(
        ("ORDER BY v.scored_at DESC, v.id DESC", "ORDER BY v.scored_at DESC, v.id ASC"),
    ),
    # "at or before merged_at" read as "before".
    "a verdict scored at the merge instant excluded": _mutate(
        ("AND v.scored_at <= j.merged_at", "AND v.scored_at < j.merged_at"),
    ),
    # A partition narrower than the PR's identity — two repos' PR #7 pooled.
    "ranking pooled across repositories": _mutate(
        (
            "PARTITION BY v.installation_id, v.github_repo_id, v.pr_number",
            "PARTITION BY v.installation_id, v.pr_number",
        ),
    ),
}


def _db(tmp_path, monkeypatch) -> str:
    url = f"sqlite:///{tmp_path}/doug.db"
    monkeypatch.setenv("DATABASE_URL", url)
    assert store.enabled()  # forces create_all() + migrations.apply()
    return url


# `uq_verdicts_app_identity` (migration 005) makes
# (installation_id, github_repo_id, pr_number, head_sha) unique for App rows —
# which is §2.1's own premise, "a PR has one verdict per head sha". Every
# seeded verdict therefore needs its own sha, exactly as five real pushes would.
_shas = itertools.count(1)


def _seed_installation(url: str, installation_id: int = INSTALLATION_ID) -> None:
    with create_engine(url).begin() as conn:
        conn.execute(
            store.installations.insert(),
            {
                "installation_id": installation_id,
                "account_login": "drewjst",
                "account_type": "User",
                "state": "active",
                "updated_at": NOW,
            },
        )


def _seed_verdict(
    url: str,
    *,
    tier: str,
    band: str,
    scored_at: datetime,
    installation_id: int = INSTALLATION_ID,
    github_repo_id: int = REPO_ID,
    pr_number: int = PR_NUMBER,
    **overrides,
) -> int:
    row = {
        "repo": REPO,
        "pr_number": pr_number,
        "scored_at": scored_at,
        "tier": tier,
        "score": 0.62 if band == "flagged" else 0.10,
        "band": band,
        "threshold": 0.30,
        "installation_id": installation_id,
        "github_repo_id": github_repo_id,
        "head_sha": f"{next(_shas):040d}",
        "source": "app",
    } | overrides
    with create_engine(url).begin() as conn:
        return conn.execute(store.verdicts.insert(), row).inserted_primary_key[0]


def _seed_outcome_job(
    url: str,
    *,
    merged_at: datetime,
    window_days: int = WINDOW_DAYS,
    installation_id: int = INSTALLATION_ID,
    github_repo_id: int = REPO_ID,
    pr_number: int = PR_NUMBER,
    merge_sha: str | None = None,
    **overrides,
) -> int:
    row = {
        "installation_id": installation_id,
        "github_repo_id": github_repo_id,
        "pr_number": pr_number,
        "merge_commit_sha": merge_sha or f"{next(_shas):040d}",
        "merged_at": merged_at,
        "base_ref": "main",
        "window_days": window_days,
        "due_at": merged_at + timedelta(days=window_days),
        "status": "pending",
        "attempts": 0,
        "created_at": merged_at,
    } | overrides
    with create_engine(url).begin() as conn:
        return conn.execute(store.outcome_jobs.insert(), row).inserted_primary_key[0]


def _preregistered_governing_ids(url: str, window: int = WINDOW_DAYS) -> list[int]:
    """§2.2's own SQL, run as text. The oracle these tests measure against."""
    with create_engine(url).begin() as conn:
        return sorted(conn.execute(text(GOVERNING_SQL), {"window": window}).scalars())


def test_the_oracle_is_still_the_locked_documents_own_sql():
    """Byte-check GOVERNING_SQL against the document it was copied from.

    Everything else in this file measures `governing_verdict` against
    GOVERNING_SQL. That is worth something only while GOVERNING_SQL is still
    §2.2's text, so the correspondence is asserted mechanically rather than
    trusted to a comment and a reviewer's eye. It fails if the locked document
    is amended, or if someone tidies the string up here — both of which are
    exactly the events that must not pass silently.
    """
    document = PREREGISTRATION.read_text()
    cte = GOVERNING_SQL.split("SELECT id FROM governing")[0].strip()
    assert cte in document, "GOVERNING_SQL is no longer §2.2's text verbatim"
    # And the half deliberately NOT copied: band qualifies the denominator in
    # §2.2's OUTER query. If it ever moves into the CTE, this selector is wrong.
    assert "AND g.band          = 'cleared';" in document


def test_selector_agrees_with_the_preregistered_sql(tmp_path, monkeypatch):
    """One locked definition, one implementation.

    A receipt that disagreed with the published table would break the only
    claim this product makes.
    """
    url = _db(tmp_path, monkeypatch)
    _seed_installation(url)
    merged_at = NOW
    early = _seed_verdict(
        url, tier="reader", band="flagged", scored_at=merged_at - timedelta(hours=2)
    )
    late = _seed_verdict(
        url, tier="reader", band="cleared", scored_at=merged_at - timedelta(minutes=5)
    )
    _seed_verdict(  # scored after the merge — advice the merger never saw
        url, tier="reader", band="cleared", scored_at=merged_at + timedelta(minutes=1)
    )
    _seed_outcome_job(url, merged_at=merged_at, window_days=14)

    expected = _preregistered_governing_ids(url)

    got = store.governing_verdict(INSTALLATION_ID, REPO_ID, PR_NUMBER, merged_at)
    assert got is not None
    assert [got["id"]] == expected == [late]
    assert got["id"] != early


def test_a_later_deterministic_verdict_does_not_displace_a_reader_one(tmp_path, monkeypatch):
    """tier='reader' filters INSIDE the ranking CTE, before row_number().

    Read off §2.1's prose alone ("the verdict with the greatest scored_at")
    and the fallback tier wins, which would publish a deterministic score as
    the read Doug sold. §2.5 gives the fallback tier its own published row
    precisely so it can never be counted as the primary instrument.
    """
    url = _db(tmp_path, monkeypatch)
    _seed_installation(url)
    merged_at = NOW
    reader_row = _seed_verdict(
        url, tier="reader", band="cleared", scored_at=merged_at - timedelta(hours=1)
    )
    _seed_verdict(
        url, tier="deterministic", band="flagged", scored_at=merged_at - timedelta(minutes=1)
    )
    # An `external` row is a human reviewer's stance with score 0.0 and no read
    # behind it (§7's separate lane). It carries the same identity columns, so
    # a tier test that only excluded 'deterministic' would let a person's
    # approval publish as Doug's verdict.
    _seed_verdict(
        url,
        tier=store.EXTERNAL_TIER,
        band="cleared",
        scored_at=merged_at - timedelta(seconds=30),
    )
    _seed_outcome_job(url, merged_at=merged_at, window_days=14)

    got = store.governing_verdict(INSTALLATION_ID, REPO_ID, PR_NUMBER, merged_at)
    assert got["id"] == reader_row
    assert _preregistered_governing_ids(url) == [reader_row]


def test_a_flagged_pr_still_has_a_governing_verdict(tmp_path, monkeypatch):
    """band='cleared' qualifies the DENOMINATOR, not the selection.

    §2.2 puts `g.band = 'cleared'` in the OUTER query. Hoisting it into the
    selector would leave every flagged PR without a receipt — and a receipt
    is the artifact a customer opens when Doug flagged the PR that broke
    them, which is the case they care about most.
    """
    url = _db(tmp_path, monkeypatch)
    _seed_installation(url)
    merged_at = NOW
    flagged = _seed_verdict(
        url, tier="reader", band="flagged", scored_at=merged_at - timedelta(hours=1)
    )
    _seed_outcome_job(url, merged_at=merged_at, window_days=14)

    got = store.governing_verdict(INSTALLATION_ID, REPO_ID, PR_NUMBER, merged_at)
    assert got["id"] == flagged
    assert got["band"] == "flagged"
    assert _preregistered_governing_ids(url) == [flagged]


def test_ties_on_scored_at_break_to_the_greatest_id(tmp_path, monkeypatch):
    """§2.1: "Ties on `scored_at` break to the greatest `verdicts.id`."

    Two pushes inside one clock tick is not exotic — `save_review` stamps
    `datetime.now(UTC)` in Python, and the tie-break is in the document
    because a rule that resolves ties by luck cannot be re-run to the same
    number by a second engineer, which is §0's whole test.
    """
    url = _db(tmp_path, monkeypatch)
    _seed_installation(url)
    merged_at = NOW
    at = merged_at - timedelta(hours=1)
    first = _seed_verdict(url, tier="reader", band="cleared", scored_at=at)
    second = _seed_verdict(url, tier="reader", band="cleared", scored_at=at)
    _seed_outcome_job(url, merged_at=merged_at, window_days=14)

    assert second > first
    got = store.governing_verdict(INSTALLATION_ID, REPO_ID, PR_NUMBER, merged_at)
    assert got["id"] == second
    assert _preregistered_governing_ids(url) == [second]


def test_no_reader_verdict_before_the_merge_returns_none(tmp_path, monkeypatch):
    """§2.4's `fallback_only` bucket: a merge with only a deterministic
    verdict has NO governing verdict under this rule, and is excluded from
    both numerator and denominator rather than counted as a clear."""
    url = _db(tmp_path, monkeypatch)
    _seed_installation(url)
    merged_at = NOW
    _seed_verdict(
        url, tier="deterministic", band="flagged", scored_at=merged_at - timedelta(hours=1)
    )
    _seed_outcome_job(url, merged_at=merged_at, window_days=14)

    assert store.governing_verdict(INSTALLATION_ID, REPO_ID, PR_NUMBER, merged_at) is None
    assert _preregistered_governing_ids(url) == []


def test_an_untenanted_verdict_never_governs(tmp_path, monkeypatch):
    """§2.6's structural exclusion, from the other side.

    CI and CLI rows carry no `installation_id` (`find_review` keys on exactly
    that null pair), and §2.2's CTE joins `j.installation_id = v.installation_id`
    so they can never reach the ranking. A receipt is an App artifact; it must
    not be served from a row that belongs to no installation.
    """
    url = _db(tmp_path, monkeypatch)
    _seed_installation(url)
    merged_at = NOW
    _seed_verdict(
        url,
        tier="reader",
        band="cleared",
        scored_at=merged_at - timedelta(minutes=1),
        installation_id=None,
        github_repo_id=None,
    )
    _seed_outcome_job(url, merged_at=merged_at, window_days=14)

    assert store.governing_verdict(INSTALLATION_ID, REPO_ID, PR_NUMBER, merged_at) is None
    assert _preregistered_governing_ids(url) == []


def test_returns_none_without_a_database(monkeypatch):
    """Same no-op posture as every other helper in store.py — no DATABASE_URL
    means no ledger, and a receipt asserts nothing rather than crashing."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert store.governing_verdict(INSTALLATION_ID, REPO_ID, PR_NUMBER, NOW) is None


# --- Agreement across the whole shape of the rule, not five chosen cases -----
#
# The five tests above each name one property. Passing all five still leaves
# the possibility that the selector and §2.2's SQL agree by coincidence on the
# handful of rows those tests happen to seed. The corpus below enumerates
# every verdict shape up to three verdicts over the axes the rule can turn on
# — tier, position relative to `merged_at` (including exactly on it), ties,
# band, whether the installation is registered, and two repositories sharing
# PR numbers — and compares the two implementations on all of them.

_CORPUS_TIERS = ("reader", "deterministic", store.EXTERNAL_TIER)
_CORPUS_OFFSETS = (
    timedelta(hours=-2),
    timedelta(minutes=-5),
    timedelta(0),  # scored at the merge instant — §2.1's "at or before"
    timedelta(minutes=1),  # after the merge, advice nobody merged on
)
_CORPUS_ALPHABET = list(itertools.product(_CORPUS_TIERS, _CORPUS_OFFSETS))
# Length 0 is the "merged with no verdict at all" case (§2.4). Repeating the
# alphabet is what produces the ties §2.1's tie-break exists for.
_CORPUS_SHAPES = [
    shape for n in range(4) for shape in itertools.product(_CORPUS_ALPHABET, repeat=n)
]
# The second repository reuses the first's PR numbers under different shapes,
# so a ranking that partitions on anything less than the full PR identity
# pools two repos' verdicts and is caught.
_COLLIDING_SHAPES = [shape for shape in _CORPUS_SHAPES if len(shape) <= 2]
_UNREGISTERED_INSTALLATION_ID = 900
_OTHER_REPO_ID = 201


def _seed_agreement_corpus(url: str) -> list[tuple[int, int, int]]:
    """Seed every shape and return the (installation, repo, pr) scenarios."""
    verdict_rows: list[dict] = []
    job_rows: list[dict] = []
    scenarios: list[tuple[int, int, int]] = []

    def emit(installation_id: int, github_repo_id: int, pr_number: int, shape) -> None:
        for position, (tier, offset) in enumerate(shape):
            verdict_rows.append(
                {
                    "repo": REPO,
                    "pr_number": pr_number,
                    "scored_at": NOW + offset,
                    "tier": tier,
                    "score": 0.62,
                    "band": ("cleared", "flagged")[position % 2],
                    "threshold": 0.30,
                    "installation_id": installation_id,
                    "github_repo_id": github_repo_id,
                    "head_sha": f"{next(_shas):040d}",
                    "source": "app",
                }
            )
        job_rows.append(
            {
                "installation_id": installation_id,
                "github_repo_id": github_repo_id,
                "pr_number": pr_number,
                "merge_commit_sha": f"{next(_shas):040d}",
                "merged_at": NOW,
                "base_ref": "main",
                "window_days": WINDOW_DAYS,
                "due_at": NOW + timedelta(days=WINDOW_DAYS),
                "status": "pending",
                "attempts": 0,
                "created_at": NOW,
            }
        )
        scenarios.append((installation_id, github_repo_id, pr_number))

    for installation_id in (INSTALLATION_ID, _UNREGISTERED_INSTALLATION_ID):
        for i, shape in enumerate(_CORPUS_SHAPES):
            emit(installation_id, REPO_ID, i + 1, shape)
        for i in range(len(_COLLIDING_SHAPES)):
            # Rotated, so the same PR number carries a different verdict set
            # under the second repo.
            emit(installation_id, _OTHER_REPO_ID, i + 1, _COLLIDING_SHAPES[i - 7])

    _seed_installation(url, INSTALLATION_ID)  # _UNREGISTERED_INSTALLATION_ID is not seeded
    with create_engine(url).begin() as conn:
        conn.execute(store.verdicts.insert(), verdict_rows)
        conn.execute(store.outcome_jobs.insert(), job_rows)
    return scenarios


def _governing_ids_by_scenario(url: str, sql: str) -> dict[tuple[int, int, int], int]:
    """Run one governing-verdict SQL and key its answers by PR identity."""
    with create_engine(url).begin() as conn:
        ids = set(conn.execute(text(sql), {"window": WINDOW_DAYS}).scalars())
        identity = {
            row["id"]: (row["installation_id"], row["github_repo_id"], row["pr_number"])
            for row in conn.execute(
                select(
                    store.verdicts.c.id,
                    store.verdicts.c.installation_id,
                    store.verdicts.c.github_repo_id,
                    store.verdicts.c.pr_number,
                )
            ).mappings()
        }
    return {identity[i]: i for i in ids}


def test_selector_matches_the_preregistered_sql_on_every_verdict_shape(tmp_path, monkeypatch):
    """The receipt and the published table, differential-tested.

    §2.2's SQL is the oracle and `governing_verdict` is the subject; they are
    written in two different languages from two readings of one locked
    document, on purpose, so that a shared misreading of §2.1 cannot pass
    green. The five named tests above say what the rule is; this one says the
    two implementations do not part company anywhere the rule can bend.
    """
    url = _db(tmp_path, monkeypatch)
    scenarios = _seed_agreement_corpus(url)
    expected = _governing_ids_by_scenario(url, GOVERNING_SQL)

    disagreements = []
    for installation_id, github_repo_id, pr_number in scenarios:
        got = store.governing_verdict(installation_id, github_repo_id, pr_number, NOW)
        want = expected.get((installation_id, github_repo_id, pr_number))
        if (got["id"] if got else None) != want:
            disagreements.append((installation_id, github_repo_id, pr_number, got, want))
    assert disagreements == []

    # Not vacuous: the corpus must contain plenty of both answers. A corpus in
    # which the rule always returns None would agree with almost any wrong
    # implementation.
    assert len(scenarios) > 3000
    assert 1000 < len(expected) < len(scenarios)


def test_the_agreement_corpus_can_catch_each_wrong_rule(tmp_path, monkeypatch):
    """Proof that the test above is not agreement on easy cases.

    Each entry in WRONG_RULES is a defect a careless reading of §2.1 would
    produce. Every one must give a different answer than §2.2 somewhere in the
    corpus — otherwise the corpus cannot tell the locked rule apart from that
    mistake, and the differential test is measuring nothing on that axis.
    """
    url = _db(tmp_path, monkeypatch)
    _seed_agreement_corpus(url)
    correct = _governing_ids_by_scenario(url, GOVERNING_SQL)

    undetected = [
        name
        for name, sql in WRONG_RULES.items()
        if _governing_ids_by_scenario(url, sql) == correct
    ]
    assert undetected == []


# --- The two places this selector is deliberately narrower than §2.2 --------


def test_both_windows_of_one_merge_share_a_governing_verdict(tmp_path, monkeypatch):
    """§2.2's `j.window_days = :window` chooses which JOBS are in scope, not
    which verdict governs. The 14- and 60-day rows for one merge are written
    atomically from the same merge facts (§6.3), so they share a `merged_at`
    and therefore a governing verdict — which is why `governing_verdict` takes
    no window argument, and why the two published rows can never disagree
    about what Doug said.
    """
    url = _db(tmp_path, monkeypatch)
    _seed_installation(url)
    merged_at = NOW
    verdict = _seed_verdict(
        url, tier="reader", band="cleared", scored_at=merged_at - timedelta(hours=1)
    )
    _seed_outcome_job(url, merged_at=merged_at, window_days=14, merge_sha="a" * 40)
    _seed_outcome_job(url, merged_at=merged_at, window_days=60, merge_sha="a" * 40)

    assert _preregistered_governing_ids(url, window=14) == [verdict]
    assert _preregistered_governing_ids(url, window=60) == [verdict]
    assert store.governing_verdict(INSTALLATION_ID, REPO_ID, PR_NUMBER, merged_at)["id"] == verdict


def test_a_twice_merged_pr_resolves_per_merge_identity(tmp_path, monkeypatch):
    """`uq_outcome_job` includes `merge_commit_sha`, so one PR can carry two
    merges at one window — which is exactly why §2.2 counts with
    `count(DISTINCT j.pr_number)`.

    This is the one case where the selector is narrower than §2.2's set query,
    and it is pinned here rather than left to be discovered. §2.2's
    `PARTITION BY` does not include the job, so its single governing row for
    the PR is the one standing at the LATEST `merged_at`. `governing_verdict`
    answers per merge identity (design spec §"One PR can have more than one
    merge identity"), so the earlier merge gets the advice that was actually
    standing when IT was merged. The published number and the receipt still
    name the same verdict for the PR's latest merge; the receipt additionally
    shows the earlier one, which a receipt should.
    """
    url = _db(tmp_path, monkeypatch)
    _seed_installation(url)
    first_merge = NOW - timedelta(days=3)
    second_merge = NOW
    before_first = _seed_verdict(
        url, tier="reader", band="flagged", scored_at=first_merge - timedelta(hours=1)
    )
    between = _seed_verdict(
        url, tier="reader", band="cleared", scored_at=second_merge - timedelta(hours=1)
    )
    _seed_outcome_job(url, merged_at=first_merge, merge_sha="a" * 40)
    _seed_outcome_job(url, merged_at=second_merge, merge_sha="b" * 40)

    # §2.2 resolves the PR as a whole to the verdict standing at the latest merge.
    assert _preregistered_governing_ids(url) == [between]
    assert (
        store.governing_verdict(INSTALLATION_ID, REPO_ID, PR_NUMBER, second_merge)["id"] == between
    )
    # ...and the receipt can still say what was standing at the first merge.
    assert (
        store.governing_verdict(INSTALLATION_ID, REPO_ID, PR_NUMBER, first_merge)["id"]
        == before_first
    )


# --- receipt() — the full document assembled on top of governing_verdict ----


def test_receipt_returns_none_without_a_database(monkeypatch):
    """Same no-op posture as every other helper in store.py — no DATABASE_URL
    means no ledger, and a receipt asserts nothing rather than crashing."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert store.receipt(INSTALLATION_ID, REPO_ID, PR_NUMBER) is None


def test_unknown_pr_returns_none(tmp_path, monkeypatch):
    """None means 'nothing at all exists for this PR' — not 'PR has no
    merges yet' (that case still returns a document; see the open-PR test
    below) and not an empty dict a caller could mistake for a real receipt."""
    url = _db(tmp_path, monkeypatch)
    _seed_installation(url)
    assert store.receipt(INSTALLATION_ID, REPO_ID, PR_NUMBER) is None


def test_open_pr_has_no_merges_and_no_governing_verdict(tmp_path, monkeypatch):
    """§2.1's rule needs a merged_at that does not exist yet."""
    url = _db(tmp_path, monkeypatch)
    _seed_installation(url)
    latest = _seed_verdict(
        url, tier="reader", band="flagged", scored_at=datetime(2026, 8, 5, tzinfo=UTC)
    )
    got = store.receipt(INSTALLATION_ID, REPO_ID, PR_NUMBER)
    assert got["merges"] == []
    assert got["latest_verdict"]["id"] == latest


def test_receipt_lists_every_merge_identity(tmp_path, monkeypatch):
    """uq_outcome_job includes merge_commit_sha, so one PR can merge twice.

    §2.2 counts with count(DISTINCT pr_number) for exactly this reason. A
    receipt that silently picked one merge would hide the other.
    """
    url = _db(tmp_path, monkeypatch)
    _seed_installation(url)
    first = datetime(2026, 8, 1, tzinfo=UTC)
    second = datetime(2026, 8, 4, tzinfo=UTC)
    _seed_verdict(url, tier="reader", band="cleared", scored_at=first - timedelta(hours=1))
    _seed_outcome_job(url, merged_at=first, window_days=14, merge_sha="aaa")
    _seed_outcome_job(url, merged_at=second, window_days=14, merge_sha="bbb")
    got = store.receipt(INSTALLATION_ID, REPO_ID, PR_NUMBER)
    assert [m["merge_commit_sha"] for m in got["merges"]] == ["aaa", "bbb"]


def test_receipt_does_not_open_a_connection_per_merge(tmp_path, monkeypatch):
    """reader:nested-connection-in-transaction: `receipt()`'s merge loop used
    to call `governing_verdict()` positionally, which opened its OWN
    `engine.connect()` per merge — a pool checkout per merge, outside
    `receipt()`'s own transaction. `receipt()` now passes its open `conn`
    through, so `governing_verdict()` opens nothing.

    Proven by instrumenting the cached engine's `connect()` — `engine.begin()`
    is itself implemented on top of one `self.connect()` call, so patching
    `connect` alone counts every checkout `receipt()` makes, direct or via
    `begin()` — and showing a 2-merge PR costs the same single checkout as a
    1-merge PR. Before the fix this was 1 for one merge and 2 for two: this
    starts failing the moment `governing_verdict()` goes back to opening its
    own connection per merge.
    """
    url = _db(tmp_path, monkeypatch)
    _seed_installation(url)
    engine = store._get_engine()
    counts = {"connect": 0}
    real_connect = engine.connect

    def counting_connect(*args, **kwargs):
        counts["connect"] += 1
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(engine, "connect", counting_connect)

    first = datetime(2026, 8, 1, tzinfo=UTC)
    second = datetime(2026, 8, 4, tzinfo=UTC)
    _seed_verdict(url, tier="reader", band="cleared", scored_at=first - timedelta(hours=1))
    _seed_outcome_job(url, merged_at=first, window_days=14, merge_sha="aaa")

    counts["connect"] = 0
    one_merge = store.receipt(INSTALLATION_ID, REPO_ID, PR_NUMBER)
    assert len(one_merge["merges"]) == 1
    one_merge_checkouts = counts["connect"]

    _seed_outcome_job(url, merged_at=second, window_days=14, merge_sha="bbb")
    counts["connect"] = 0
    two_merges = store.receipt(INSTALLATION_ID, REPO_ID, PR_NUMBER)
    assert len(two_merges["merges"]) == 2
    two_merge_checkouts = counts["connect"]

    assert one_merge_checkouts == two_merge_checkouts == 1


def test_merged_pr_without_a_reader_verdict_reports_null_governing(tmp_path, monkeypatch):
    """Never substituted with the latest verdict."""
    url = _db(tmp_path, monkeypatch)
    _seed_installation(url)
    merged_at = datetime(2026, 8, 5, tzinfo=UTC)
    _seed_verdict(
        url, tier="deterministic", band="flagged", scored_at=merged_at - timedelta(hours=1)
    )
    _seed_outcome_job(url, merged_at=merged_at, window_days=14)
    got = store.receipt(INSTALLATION_ID, REPO_ID, PR_NUMBER)
    assert got["merges"][0]["governing_verdict"] is None
    assert got["latest_verdict"] is not None


def test_both_windows_appear_under_their_merge(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    _seed_installation(url)
    merged_at = datetime(2026, 8, 5, tzinfo=UTC)
    _seed_verdict(url, tier="reader", band="cleared", scored_at=merged_at - timedelta(hours=1))
    _seed_outcome_job(url, merged_at=merged_at, window_days=14, merge_sha="aaa")
    _seed_outcome_job(url, merged_at=merged_at, window_days=60, merge_sha="aaa")
    got = store.receipt(INSTALLATION_ID, REPO_ID, PR_NUMBER)
    assert len(got["merges"]) == 1
    assert sorted(a["window_days"] for a in got["merges"][0]["adjudication"]) == [14, 60]


def test_exactly_one_merge_is_publication_governing(tmp_path, monkeypatch):
    """§2.2 designates ONE governing verdict per PR, at the latest merge.

    The receipt shows every merge, so without this flag an earlier merge's
    standing verdict reads as though it governed publication. It did not.
    """
    url = _db(tmp_path, monkeypatch)
    _seed_installation(url)
    first_merge = NOW - timedelta(days=3)
    second_merge = NOW
    _seed_verdict(url, tier="reader", band="flagged", scored_at=first_merge - timedelta(hours=1))
    _seed_verdict(url, tier="reader", band="cleared", scored_at=second_merge - timedelta(hours=1))
    _seed_outcome_job(url, merged_at=first_merge, merge_sha="a" * 40)
    _seed_outcome_job(url, merged_at=second_merge, merge_sha="b" * 40)

    got = store.receipt(INSTALLATION_ID, REPO_ID, PR_NUMBER)
    flags = [m["publication_governing"] for m in got["merges"]]
    assert flags.count(True) == 1
    latest = max(got["merges"], key=lambda m: m["merged_at"])
    assert latest["publication_governing"] is True


def test_a_later_external_review_never_becomes_latest_verdict(tmp_path, monkeypatch):
    """save_external_review writes an external-tier row into the SAME
    identity tuple as a reader verdict — api.py's pull_request_review webhook
    handler calls it on every human review, with scored_at set to the
    reviewer's own submitted_at. On any PR a human approves after Doug's
    last score — the ordinary case — that row is newest by scored_at and
    would win `latest`'s plain ORDER BY scored_at DESC without the same
    tier exclusion its five sibling queries all carry.

    Without that exclusion this surfaces save_external_review's 0.0/0.0
    score/threshold placeholders — written because no model ran and no diff
    was read — as though they were the newest thing Doug had said about
    this PR.
    """
    url = _db(tmp_path, monkeypatch)
    _seed_installation(url)
    reader_id = _seed_verdict(
        url, tier="reader", band="cleared", scored_at=NOW - timedelta(hours=1)
    )
    store.save_external_review(
        INSTALLATION_ID,
        REPO_ID,
        REPO,
        PR_NUMBER,
        f"{next(_shas):040d}",
        "review:alice",
        Band.CLEARED,
        NOW,
    )
    got = store.receipt(INSTALLATION_ID, REPO_ID, PR_NUMBER)
    assert got["latest_verdict"]["id"] == reader_id
    assert got["latest_verdict"]["tier"] == "reader"


# --- store.repo_id_for — the operator path's name resolution ----------------
#
# The tenant path never reaches this function (see the endpoint section
# below). These tests pin what it resolves THROUGH: installation_repos in an
# active state, never verdicts.repo, which is display text (MT4).


def test_repo_id_for_resolves_an_active_repo(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    store.set_installation_repos(INSTALLATION_ID, [(REPO_ID, REPO)], replace=False)
    assert store.repo_id_for(REPO) == (INSTALLATION_ID, REPO_ID)


def test_repo_id_for_ignores_a_removed_repo(tmp_path, monkeypatch):
    """A repo removed from its installation keeps its row — its verdicts still
    have to resolve to something — but must stop being reachable by name."""
    _db(tmp_path, monkeypatch)
    store.set_installation_repos(INSTALLATION_ID, [(REPO_ID, REPO)], replace=False)
    store.set_installation_repos(INSTALLATION_ID, [(REPO_ID, REPO)], replace=False, state="removed")
    assert store.repo_id_for(REPO) is None


def test_repo_id_for_does_not_resolve_through_verdicts_repo(tmp_path, monkeypatch):
    """MT4: `verdicts.repo` is display text and is not the tenancy record.

    A ledger with verdicts for a repo that has no installation_repos row is
    not hypothetical — it is exactly the drift
    count_verdict_repos_missing_from_ledger() exists to shout about. Resolving
    a name through it would hand out ids nothing authorises.
    """
    url = _db(tmp_path, monkeypatch)
    _seed_installation(url)
    _seed_verdict(url, tier="reader", band="cleared", scored_at=NOW)
    assert store.repo_id_for(REPO) is None


def test_repo_id_for_returns_none_for_an_unknown_name(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    store.set_installation_repos(INSTALLATION_ID, [(REPO_ID, REPO)], replace=False)
    assert store.repo_id_for("nobody/nothing") is None


def test_repo_id_for_returns_none_without_a_database(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert store.repo_id_for(REPO) is None


def test_repo_id_for_breaks_a_name_collision_deterministically(tmp_path, monkeypatch):
    """One full_name can be active under two installations — a transfer
    mid-flight, or a repositories_removed delivery that never arrived. There
    is no right answer available here, so the answer must at least be the
    same one every time rather than whichever row the planner returns first.
    """
    _db(tmp_path, monkeypatch)
    store.set_installation_repos(INSTALLATION_ID, [(REPO_ID, REPO)], replace=False)
    store.set_installation_repos(_OTHER_INSTALLATION_ID, [(_SIBLING_REPO_ID, REPO)], replace=False)
    newest = (_OTHER_INSTALLATION_ID, _SIBLING_REPO_ID)
    assert store.repo_id_for(REPO) == newest
    assert [store.repo_id_for(REPO) for _ in range(5)].count(newest) == 5


def test_repo_id_for_shouts_about_a_name_collision(tmp_path, monkeypatch, capsys):
    """Answering is not the same as accepting. Two active registrations for
    one name is itself a ledger bug — a transfer that half-landed, or a
    repositories_removed delivery that never arrived — and the operator is
    exactly who should learn about it.

    Newest-wins keeps the endpoint answering rather than 500ing on an anomaly
    it did not cause; the log is what stops that anomaly being invisible. Same
    posture as reconcile's open-PR cap (worker.py:454), which does the bounded
    thing AND says it did.
    """
    _db(tmp_path, monkeypatch)
    store.set_installation_repos(INSTALLATION_ID, [(REPO_ID, REPO)], replace=False)
    store.set_installation_repos(_OTHER_INSTALLATION_ID, [(_SIBLING_REPO_ID, REPO)], replace=False)
    capsys.readouterr()  # discard whatever the seeding wrote
    assert store.repo_id_for(REPO) == (_OTHER_INSTALLATION_ID, _SIBLING_REPO_ID)

    err = capsys.readouterr().err
    assert "DRIFT" in err
    assert REPO in err
    # BOTH sides named, and the ids too: the operator's next move is to go
    # look at a specific installation_repos row, and a line that says only
    # "there was a collision" does not tell them which one.
    assert str(INSTALLATION_ID) in err and str(_OTHER_INSTALLATION_ID) in err
    assert str(REPO_ID) in err and str(_SIBLING_REPO_ID) in err


def test_repo_id_for_is_quiet_on_the_ordinary_case(tmp_path, monkeypatch, capsys):
    """A line that fires on the normal case is one an operator learns to
    scroll past — which costs exactly the signal the line exists to carry.
    Same reason REVIEW_STATES_WITHOUT_A_STANCE is written down and NOT
    logged (api.py): only the thing nobody chose gets to be loud.
    """
    _db(tmp_path, monkeypatch)
    store.set_installation_repos(INSTALLATION_ID, [(REPO_ID, REPO)], replace=False)
    capsys.readouterr()
    assert store.repo_id_for(REPO) == (INSTALLATION_ID, REPO_ID)
    assert capsys.readouterr().err == ""


# --- GET /v1/prs/{n}/receipt — the endpoint ---------------------------------
#
# One evidentiary record, served under two token classes, on a service
# deployed --allow-unauthenticated. The property this section exists to pin is
# not "the route works": it is that no request carrying a dispensed key can be
# answered from another installation's ledger rows, and that a caller who asks
# for a repo they may not see learns nothing at all — not even that it exists.
#
# Dispensed keys here are REAL, minted through tenancy.mint_key rather than
# simulated by monkeypatching tenancy.resolve. The subject is the whole chain
# — a key's frozen selection intersected against the live ledger — and a
# stubbed resolve would only prove that the route trusts whatever context it
# is handed, which is the half of the chain that was never in doubt.

OPERATOR = "t0ken"
AUTH = {"X-Doug-Token": OPERATOR}
_SIBLING_REPO_ID = 300
_SIBLING_REPO = "drewjst/sidecar"
_OTHER_INSTALLATION_ID = 999
MERGE_SHA = "a" * 40
SECOND_MERGE_SHA = "b" * 40


def _http_db(tmp_path, monkeypatch) -> str:
    """A ledger, the operator secret, and a pepper — what these routes need.

    The pepper is what makes tenancy.resolve able to verify a real key at
    all; without it every dispensed token raises KeysNotConfigured and the
    tenancy tests below would pass on a 503 that proves nothing.
    """
    monkeypatch.setenv("DOUG_API_TOKEN", OPERATOR)
    monkeypatch.setenv("DOUG_TOKEN_PEPPER", base64.b64encode(b"p" * 32).decode())
    return _db(tmp_path, monkeypatch)


def _seed_outcome(
    url: str,
    *,
    kind: str,
    merge_sha: str,
    window_days: int = WINDOW_DAYS,
    installation_id: int = INSTALLATION_ID,
    github_repo_id: int = REPO_ID,
    pr_number: int = PR_NUMBER,
    repo: str = REPO,
    detail: dict | None = None,
) -> None:
    """One adjudicated window, written the way the adjudicator writes it —
    identity columns populated and `detail` JSON-encoded into a TEXT column."""
    with create_engine(url).begin() as conn:
        conn.execute(
            store.outcomes.insert(),
            {
                "repo": repo,
                "pr_number": pr_number,
                "kind": kind,
                "observed_at": NOW,
                "source": "git-labels",
                "github_repo_id": github_repo_id,
                "installation_id": installation_id,
                "window_days": window_days,
                "merge_commit_sha": merge_sha,
                "detail": json.dumps(detail) if detail is not None else None,
            },
        )


def _seed_full_pr(
    url: str,
    *,
    installation_id: int = INSTALLATION_ID,
    github_repo_id: int = REPO_ID,
    full_name: str = REPO,
    pr_number: int = PR_NUMBER,
    merged_at: datetime = NOW,
    merge_sha: str = MERGE_SHA,
    base_ref: str = "main",
    diff_budget: int | None = 60_000,
    read_order: str | None = "risk-first",
    outcome_kind: str | None = None,
    detail: dict | None = None,
) -> int:
    """One merged PR end to end: installation, repo, reader verdict, merge.

    The installation_repos row is not decoration — it is the ONLY thing that
    makes the repo resolvable by name, on either token path.
    """
    _seed_installation(url, installation_id)
    store.set_installation_repos(installation_id, [(github_repo_id, full_name)], replace=False)
    verdict_id = _seed_verdict(
        url,
        tier="reader",
        band="flagged",
        scored_at=merged_at - timedelta(hours=1),
        installation_id=installation_id,
        github_repo_id=github_repo_id,
        pr_number=pr_number,
        repo=full_name,
        diff_budget=diff_budget,
        read_order=read_order,
    )
    _seed_outcome_job(
        url,
        merged_at=merged_at,
        installation_id=installation_id,
        github_repo_id=github_repo_id,
        pr_number=pr_number,
        merge_sha=merge_sha,
        base_ref=base_ref,
    )
    if outcome_kind is not None:
        _seed_outcome(
            url,
            kind=outcome_kind,
            merge_sha=merge_sha,
            installation_id=installation_id,
            github_repo_id=github_repo_id,
            pr_number=pr_number,
            repo=full_name,
            detail=detail,
        )
    return verdict_id


def _mint_for(
    url: str,
    installation_id: int,
    *,
    repo_ids: list[int] | None = None,
    scopes: list[str] | None = None,
) -> str:
    """A real dispensed key. `scopes=None` keeps whatever mint_key grants."""
    minted = tenancy.mint_key(
        installation_id,
        repo_selection="selected" if repo_ids else "all",
        repo_ids=list(repo_ids or []),
        label=None,
        expires_in_days=0,
        minted_by="drewjst",
    )
    if scopes is not None:
        with create_engine(url).begin() as conn:
            conn.execute(
                store.installation_tokens.update()
                .where(store.installation_tokens.c.id == minted.token_id)
                .values(scopes=scopes)
            )
    return minted.token


def _get(token: str, pr_number: int = PR_NUMBER, repo: str = REPO):
    return TestClient(app).get(
        f"/v1/prs/{pr_number}/receipt",
        params={"repo": repo},
        headers={"X-Doug-Token": token},
    )


def test_operator_token_reads_any_receipt(tmp_path, monkeypatch):
    url = _http_db(tmp_path, monkeypatch)
    _seed_full_pr(url)
    r = _get(OPERATOR)
    assert r.status_code == 200
    body = r.json()
    assert body["pr_number"] == PR_NUMBER
    assert body["repo"] == REPO
    assert body["latest_verdict"]["band"] == "flagged"
    assert body["merges"][0]["merge_commit_sha"] == MERGE_SHA


def test_tenant_key_reads_its_own_receipt(tmp_path, monkeypatch):
    """The pass side, and it is load-bearing: every 404 below would also be
    satisfied by a route that simply refused every dispensed key."""
    url = _http_db(tmp_path, monkeypatch)
    _seed_full_pr(url)
    r = _get(_mint_for(url, INSTALLATION_ID))
    assert r.status_code == 200
    assert r.json()["pr_number"] == PR_NUMBER


def test_cross_tenant_token_gets_404_not_403(tmp_path, monkeypatch):
    """The same code — and the same BODY — a nonexistent repo gets.

    A 403 would confirm the repo exists. So would a distinct message, and so
    would a 200 carrying an empty document. This is the one failure in the
    receipts stack that cannot be walked back: it hands one customer a probe
    for another customer's private repository names.
    """
    url = _http_db(tmp_path, monkeypatch)
    _seed_full_pr(url, installation_id=INSTALLATION_ID)
    _seed_installation(url, _OTHER_INSTALLATION_ID)
    store.set_installation_repos(
        _OTHER_INSTALLATION_ID, [(_SIBLING_REPO_ID, "someone/else")], replace=False
    )
    other = _mint_for(url, _OTHER_INSTALLATION_ID)

    refused = _get(other, repo=REPO)
    ghost = _get(other, repo="nobody/nothing")
    assert refused.status_code == 404
    assert ghost.status_code == 404
    assert refused.json() == ghost.json(), "the two answers must be indistinguishable"


def test_selected_key_cannot_read_a_sibling_repos_receipt(tmp_path, monkeypatch):
    """MT1 at the receipt surface: repo scope binds INSIDE one installation
    too. Same installation, same tenant, a repo the key was not cut for."""
    url = _http_db(tmp_path, monkeypatch)
    _seed_full_pr(url)
    store.set_installation_repos(
        INSTALLATION_ID, [(_SIBLING_REPO_ID, _SIBLING_REPO)], replace=False
    )
    token = _mint_for(url, INSTALLATION_ID, repo_ids=[_SIBLING_REPO_ID])
    assert _get(token, repo=REPO).status_code == 404


def test_the_tenant_path_never_resolves_through_repo_id_for(tmp_path, monkeypatch):
    """repo_id_for searches every installation and intersects against nothing.

    Reaching it with a dispensed key would resolve a name the caller may have
    no relationship with at all — the 404s above would still be 404s, but the
    IN-SCOPE answer would be served from ids nobody checked against the key.
    Both branches are exercised so a route that only avoided it on the refusal
    path is still caught.
    """
    url = _http_db(tmp_path, monkeypatch)
    _seed_full_pr(url)
    token = _mint_for(url, INSTALLATION_ID)

    def _boom(full_name):
        raise AssertionError(f"repo_id_for reached with a dispensed key: {full_name!r}")

    monkeypatch.setattr(store, "repo_id_for", _boom)
    assert _get(token, repo=REPO).status_code == 200
    assert _get(token, repo="someone/else").status_code == 404


def test_queue_only_key_is_refused(tmp_path, monkeypatch):
    """The scopes column is the gate, not the fact that a key resolves. 401
    rather than 403, matching /v1/queue: a scope it does not hold is not a
    door it may knock on."""
    url = _http_db(tmp_path, monkeypatch)
    _seed_full_pr(url)
    token = _mint_for(url, INSTALLATION_ID, scopes=["queue:read"])
    assert _get(token).status_code == 401


def test_unresolvable_token_is_401(tmp_path, monkeypatch):
    url = _http_db(tmp_path, monkeypatch)
    _seed_full_pr(url)
    assert _get("doug_nope").status_code == 401


def test_unknown_repo_is_404(tmp_path, monkeypatch):
    url = _http_db(tmp_path, monkeypatch)
    _seed_full_pr(url)
    assert _get(OPERATOR, repo="nobody/nothing").status_code == 404


def test_unknown_pr_is_404(tmp_path, monkeypatch):
    """The repo resolves and the caller is the operator — the PR simply is not
    there. Same code a repo outside a caller's scope gets, on purpose."""
    url = _http_db(tmp_path, monkeypatch)
    _seed_full_pr(url)
    assert _get(OPERATOR, pr_number=999).status_code == 404


def test_a_removed_repo_stops_resolving(tmp_path, monkeypatch):
    """installation_repos.state is the authority, and the verdicts left behind
    are not a second way in. Rows are never deleted, so without the state
    filter the name would keep resolving forever after the uninstall."""
    url = _http_db(tmp_path, monkeypatch)
    _seed_full_pr(url)
    assert _get(OPERATOR).status_code == 200
    store.set_installation_repos(INSTALLATION_ID, [(REPO_ID, REPO)], replace=True, state="removed")
    assert _get(OPERATOR).status_code == 404


def test_receipt_503s_without_the_operator_token_configured(tmp_path, monkeypatch):
    """A missing operator secret is a broken deployment, not a bad request —
    and tenant traffic must not paper over it (same posture as /v1/queue)."""
    url = _db(tmp_path, monkeypatch)
    monkeypatch.delenv("DOUG_API_TOKEN", raising=False)
    _seed_full_pr(url)
    assert _get("anything").status_code == 503


def test_receipt_503s_without_a_ledger(monkeypatch):
    """Checked BEFORE the token, deliberately: with no ledger tenancy.resolve
    can read no key at all, so a dispensed token would come back 401 'bad
    token' and tell a customer their key is broken when the deployment is."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DOUG_API_TOKEN", OPERATOR)
    assert _get(OPERATOR).status_code == 503


def test_read_configuration_absent_renders_as_not_recorded(tmp_path, monkeypatch):
    """Never a number the ledger cannot support. Every verdict scored before
    migration 008 has neither column, and `recorded` is the one boolean that
    stops a consumer reading absence as a value."""
    url = _http_db(tmp_path, monkeypatch)
    _seed_full_pr(url, diff_budget=None, read_order=None)
    read = _get(OPERATOR).json()["latest_verdict"]["read"]
    assert read["diff_budget"] is None and read["read_order"] is None
    assert read["recorded"] is False


@pytest.mark.parametrize(
    "diff_budget,read_order",
    [(60_000, None), (None, "risk-first")],
)
def test_a_half_stamped_read_is_not_recorded(tmp_path, monkeypatch, diff_budget, read_order):
    """EITHER column NULL means no configuration was recorded. A budget with
    no ordering does not say which part of the diff the model was given, and
    an ordering with no budget does not say how much of it — half a pair
    describes no instrument, so it must not read as a described one."""
    url = _http_db(tmp_path, monkeypatch)
    _seed_full_pr(url, diff_budget=diff_budget, read_order=read_order)
    read = _get(OPERATOR).json()["latest_verdict"]["read"]
    assert read["recorded"] is False


def test_a_fully_stamped_read_is_recorded(tmp_path, monkeypatch):
    url = _http_db(tmp_path, monkeypatch)
    _seed_full_pr(url, diff_budget=60_000, read_order="risk-first")
    read = _get(OPERATOR).json()["latest_verdict"]["read"]
    assert read == {"diff_budget": 60_000, "read_order": "risk-first", "recorded": True}


def test_only_the_latest_merge_is_publication_governing(tmp_path, monkeypatch):
    url = _http_db(tmp_path, monkeypatch)
    _seed_full_pr(url, merged_at=NOW - timedelta(days=3), merge_sha=MERGE_SHA)
    _seed_verdict(url, tier="reader", band="cleared", scored_at=NOW - timedelta(hours=1))
    _seed_outcome_job(url, merged_at=NOW, merge_sha=SECOND_MERGE_SHA)
    merges = _get(OPERATOR).json()["merges"]
    assert [m["publication_governing"] for m in merges] == [False, True]


def test_a_non_governing_merge_says_so_in_words(tmp_path, monkeypatch):
    """A bare `false` is not enough, and the reason is what sits beside it.

    The earlier merge carries its own real governing_verdict in the same
    document — the advice that was standing when THAT commit landed. To a
    person reading the receipt after an incident, that verdict looks exactly
    like the one the published quarterly number used. It is not: §2.2
    designates one governing verdict per PR, at the latest merge. The
    sentence is what closes that gap; a flag alone leaves the reader to
    infer it.
    """
    url = _http_db(tmp_path, monkeypatch)
    _seed_full_pr(url, merged_at=NOW - timedelta(days=3), merge_sha=MERGE_SHA)
    _seed_verdict(url, tier="reader", band="cleared", scored_at=NOW - timedelta(hours=1))
    _seed_outcome_job(url, merged_at=NOW, merge_sha=SECOND_MERGE_SHA)

    earlier, latest = _get(OPERATOR).json()["merges"]
    assert earlier["governing_verdict"] is not None, "the misreading needs something to misread"
    assert earlier["publication_note"] == api.NOT_PUBLICATION_GOVERNING_NOTE
    assert latest["publication_note"] == api.PUBLICATION_GOVERNING_NOTE
    assert earlier["publication_note"] != latest["publication_note"]
    # The flag and the words must not be able to drift apart.
    assert "did not govern" in api.NOT_PUBLICATION_GOVERNING_NOTE.lower()


def test_a_real_outcome_lands_under_its_own_merge_and_window(tmp_path, monkeypatch):
    """receipt()'s outcomes join, exercised with rows actually in it.

    Every other test in this file leaves `outcomes` empty, so that join has
    only ever run its no-rows branch and the keys it joins on —
    (merge_commit_sha, window_days) — were never proved by anything that
    could fail. Two merges x two windows, three distinct adjudications and
    one deliberately absent: a join that dropped either key would pool them,
    and a receipt that attributed one merge's revert to another merge is a
    false statement about which commit broke production.
    """
    url = _http_db(tmp_path, monkeypatch)
    first, second = NOW - timedelta(days=3), NOW
    _seed_full_pr(url, merged_at=first, merge_sha=MERGE_SHA)
    _seed_outcome_job(url, merged_at=first, window_days=60, merge_sha=MERGE_SHA)
    _seed_outcome_job(url, merged_at=second, window_days=14, merge_sha=SECOND_MERGE_SHA)
    _seed_outcome_job(url, merged_at=second, window_days=60, merge_sha=SECOND_MERGE_SHA)
    _seed_outcome(url, kind="clean", merge_sha=MERGE_SHA, window_days=14)
    _seed_outcome(
        url,
        kind="revert",
        merge_sha=MERGE_SHA,
        window_days=60,
        detail={"anchor_sha": MERGE_SHA, "revert_sha": "c" * 40},
    )
    _seed_outcome(url, kind="censored", merge_sha=SECOND_MERGE_SHA, window_days=14)
    # (SECOND_MERGE_SHA, 60) is left unadjudicated on purpose: an open window
    # must stay null rather than inherit a sibling's answer.

    merges = _get(OPERATOR).json()["merges"]
    got = {
        (m["merge_commit_sha"], a["window_days"]): a["kind"]
        for m in merges
        for a in m["adjudication"]
    }
    assert got == {
        (MERGE_SHA, 14): "clean",
        (MERGE_SHA, 60): "revert",
        (SECOND_MERGE_SHA, 14): "censored",
        (SECOND_MERGE_SHA, 60): None,
    }
    revert = next(a for a in merges[0]["adjudication"] if a["window_days"] == 60)
    # Decoded, not handed back as the JSON string the TEXT column holds.
    assert revert["detail"]["revert_sha"] == "c" * 40
    assert revert["observed_at"] is not None and revert["source"] == "git-labels"


def test_censored_merge_never_reads_clean(tmp_path, monkeypatch):
    """§6.2: censored is not survival — it is a window nobody could observe.

    Rendering it as clean would publish evidence that was never gathered, on
    the artifact a customer opens precisely because they do not trust the
    summary number.
    """
    url = _http_db(tmp_path, monkeypatch)
    _seed_full_pr(url, base_ref="release/1.x", outcome_kind="censored")
    merge = _get(OPERATOR).json()["merges"][0]
    kinds = [a["kind"] for a in merge["adjudication"]]
    assert "clean" not in kinds
    assert "censored" in kinds
    assert merge["base_ref"] == "release/1.x"


def test_an_open_pr_serves_a_receipt_with_no_merges(tmp_path, monkeypatch):
    """A PR Doug has scored but nobody has merged is a real receipt, not a
    404: "what has Doug said about this" is answerable before the merge."""
    url = _http_db(tmp_path, monkeypatch)
    _seed_installation(url)
    store.set_installation_repos(INSTALLATION_ID, [(REPO_ID, REPO)], replace=False)
    _seed_verdict(url, tier="reader", band="flagged", scored_at=NOW)
    body = _get(OPERATOR).json()
    assert body["merges"] == []
    assert body["latest_verdict"]["band"] == "flagged"


def test_the_governing_verdict_is_not_silently_the_latest_one(tmp_path, monkeypatch):
    """The gap the whole document exists to preserve: the PR was rescored
    after it merged, so the newest thing Doug has said is NOT the advice the
    merger acted on. Collapsing the two would erase the fact a reader of an
    incident review came for."""
    url = _http_db(tmp_path, monkeypatch)
    governing = _seed_full_pr(url)
    later = _seed_verdict(
        url, tier="reader", band="cleared", scored_at=NOW + timedelta(hours=2)
    )
    body = _get(OPERATOR).json()
    assert body["latest_verdict"]["verdict_id"] == later
    assert body["merges"][0]["governing_verdict"]["verdict_id"] == governing


def test_pending_adjudication_reports_the_in_force_hash(tmp_path, monkeypatch):
    """A window with no stamped hash is governed by whatever document is
    currently in force — the receipt says so, labelled as such, because that
    is the document that will govern it once the window closes."""
    url = _http_db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_PREREG_HASH", "f" * 64)
    _seed_full_pr(url)  # outcome_kind=None: the window is still pending.
    body = _get(OPERATOR).json()
    assert body["preregistration"] == {"hash": "f" * 64, "in_force": True}
    assert body["merges"][0]["adjudication"][0]["prereg_hash"] is None


def test_adjudicated_entry_keeps_the_hash_it_was_judged_under(tmp_path, monkeypatch):
    """A receipt must not reprint today's hash over an older adjudication —
    that would manufacture a confident-but-derived claim about which document
    actually governed it."""
    url = _http_db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_PREREG_HASH", "f" * 64)
    _seed_full_pr(url, outcome_kind="clean", detail={"prereg_hash": "a" * 64})
    body = _get(OPERATOR).json()
    entry = body["merges"][0]["adjudication"][0]
    assert entry["prereg_hash"] == "a" * 64
    assert body["preregistration"]["hash"] == "f" * 64


def test_missing_prereg_hash_env_var_renders_as_not_in_force(tmp_path, monkeypatch):
    """Local dev and the test suite never set DOUG_PREREG_HASH. Absence must
    render as a plain fact — False and None — never a crash or a fabricated
    value."""
    url = _http_db(tmp_path, monkeypatch)
    monkeypatch.delenv("DOUG_PREREG_HASH", raising=False)
    _seed_full_pr(url)
    body = _get(OPERATOR).json()
    assert body["preregistration"] == {"hash": None, "in_force": False}


# --- A receipt across its repository's transfer (#250) ----------------------
#
# A GitHub transfer moves a repository between installations while
# `github_repo_id` stays put, so rows written before the move keep the old
# installation forever. #251 widened the SESSION read paths and /v1/queue to
# a repository's installation lineage and left this route pinned, which meant
# every run scored before 2026-08-26 answered 404 here — on all three paths
# into it, the operator's included.
#
# The property these pin is the one that makes the fix worth having AND safe:
# widening WHOSE rows may be read never widens WHICH repository, because the
# `github_repo_id` every query below already pins IS the pairing
# `_tenant_ids` demands.

_OLD_INSTALLATION_ID = 150424894
_NEW_INSTALLATION_ID = 153075663
_MOVED_REPO_ID = 1314318717
_OLD_NAME = "drewjst/doug"
_NEW_NAME = "coldworkshq/doug"
_PR_BEFORE = 42
_PR_AFTER = 99


def _transferred_repo(tmp_path, monkeypatch) -> str:
    """One repository, moved, with a merged PR on each side of the move.

    The old registration is left at state='removed' rather than deleted,
    which is the shape production is actually in (migration 17's note, and
    #228's already-fired hazard): the junction row is history, and this is
    the read that history exists for.
    """
    url = _http_db(tmp_path, monkeypatch)
    _seed_full_pr(
        url,
        installation_id=_OLD_INSTALLATION_ID,
        github_repo_id=_MOVED_REPO_ID,
        full_name=_OLD_NAME,
        pr_number=_PR_BEFORE,
        merge_sha=MERGE_SHA,
        outcome_kind="clean",
    )
    store.set_installation_repos(
        _OLD_INSTALLATION_ID, [(_MOVED_REPO_ID, _OLD_NAME)], replace=False, state="removed"
    )
    _seed_full_pr(
        url,
        installation_id=_NEW_INSTALLATION_ID,
        github_repo_id=_MOVED_REPO_ID,
        full_name=_NEW_NAME,
        pr_number=_PR_AFTER,
        merged_at=NOW + timedelta(days=2),
        merge_sha=SECOND_MERGE_SHA,
        outcome_kind="clean",
    )
    return url


def test_a_receipt_survives_its_repositorys_transfer(tmp_path, monkeypatch):
    """The issue, stated as a test: a PR scored before its repo moved renders
    the same document as one scored after, under a key on the new
    installation. Both sides are asserted, because a route that simply served
    every receipt to everybody would also pass the first assertion."""
    url = _transferred_repo(tmp_path, monkeypatch)
    token = _mint_for(url, _NEW_INSTALLATION_ID)

    after = _get(token, pr_number=_PR_AFTER, repo=_NEW_NAME)
    before = _get(token, pr_number=_PR_BEFORE, repo=_NEW_NAME)

    assert after.status_code == 200
    assert before.status_code == 200
    assert before.json()["pr_number"] == _PR_BEFORE
    assert before.json()["latest_verdict"]["band"] == "flagged"
    assert before.json()["merges"][0]["merge_commit_sha"] == MERGE_SHA
    assert before.json()["merges"][0]["adjudication"][0]["kind"] == "clean"


def test_the_operator_reads_a_receipt_from_before_the_transfer(tmp_path, monkeypatch):
    """The operator path pinned the same way and was not named in #250.
    `repo_id_for` resolves the CURRENT registration, so the operator token —
    the one credential with no scope at all — could not reach a historical
    receipt either."""
    _transferred_repo(tmp_path, monkeypatch)
    r = _get(OPERATOR, pr_number=_PR_BEFORE, repo=_NEW_NAME)
    assert r.status_code == 200
    assert r.json()["merges"][0]["merge_commit_sha"] == MERGE_SHA


def test_a_transferred_receipt_still_names_a_governing_verdict(tmp_path, monkeypatch):
    """The half of the fix that a status code cannot see.

    `receipt` resolves each merge's governing verdict from the MERGE ROW'S own
    installation, not the caller's. Passing the caller's would leave this
    field null on every pre-transfer merge — a receipt that renders, states
    that a merge happened, and quietly claims Doug had said nothing about it,
    which is worse than the 404 it replaced.
    """
    url = _transferred_repo(tmp_path, monkeypatch)
    token = _mint_for(url, _NEW_INSTALLATION_ID)
    merge = _get(token, pr_number=_PR_BEFORE, repo=_NEW_NAME).json()["merges"][0]
    assert merge["governing_verdict"] is not None
    assert merge["governing_verdict"]["band"] == "flagged"
    assert merge["publication_governing"] is True


def test_the_lineage_widens_installations_but_never_repositories(tmp_path, monkeypatch):
    """`github_repo_id` is the tenancy boundary, and after this widening it is
    the ONLY one left inside `receipt`.

    Tested against `store.receipt` directly rather than through the route,
    deliberately: the route refuses an out-of-scope repo by name before the
    ledger is touched, so an HTTP test passes whether or not the queries
    underneath still pin the repository. Dropping any of those three pins
    would leak a sibling repository's rows into this document and no other
    test in this file would notice — the sibling's verdict here is the NEWER
    one, so it would win `latest_verdict` outright.

    Two of the three pins are killed by this test: `verdicts` and
    `outcome_jobs`. The `outcomes` pin is NOT, and cannot be from out here.
    `by_outcome` keys on `(merge_commit_sha, window_days)`, so a sibling
    repository's outcome can only reach the document by colliding with a real
    merge sha, and which of the two then wins the dict is query order — a
    test asserting that on sqlite would claim a guarantee Postgres does not
    give. The pin stays because defence in depth is cheaper than the argument
    that git makes the collision impossible; it is documented as unguarded
    rather than guarded by a test that proves nothing.
    """
    url = _transferred_repo(tmp_path, monkeypatch)
    # A second repository on the retired installation: in the lineage's
    # installations, never in this repository's identity.
    store.set_installation_repos(
        _OLD_INSTALLATION_ID, [(_SIBLING_REPO_ID, "drewjst/private")], replace=False
    )
    _seed_verdict(
        url,
        tier="reader",
        band="cleared",
        scored_at=NOW + timedelta(days=30),
        installation_id=_OLD_INSTALLATION_ID,
        github_repo_id=_SIBLING_REPO_ID,
        pr_number=_PR_BEFORE,
        repo="drewjst/private",
    )
    _seed_outcome_job(
        url,
        merged_at=NOW + timedelta(days=30),
        installation_id=_OLD_INSTALLATION_ID,
        github_repo_id=_SIBLING_REPO_ID,
        pr_number=_PR_BEFORE,
        merge_sha="d" * 40,
    )

    lineage = frozenset({_OLD_INSTALLATION_ID, _NEW_INSTALLATION_ID})
    doc = store.receipt(None, _MOVED_REPO_ID, _PR_BEFORE, installation_ids=lineage)

    assert doc["latest_verdict"]["band"] == "flagged", "the sibling's verdict leaked in"
    assert [m["merge_commit_sha"] for m in doc["merges"]] == [MERGE_SHA]


def test_an_installation_that_never_held_the_repo_stays_unreadable(tmp_path, monkeypatch):
    """The other direction: a matching `github_repo_id` is not on its own a
    licence to read another installation's rows. Only installations that
    provably registered THIS repository join the lineage, so a stranger's row
    carrying the same repo id must not surface as a merge on this receipt."""
    url = _transferred_repo(tmp_path, monkeypatch)
    _seed_installation(url, _OTHER_INSTALLATION_ID)
    _seed_outcome_job(
        url,
        merged_at=NOW + timedelta(days=5),
        installation_id=_OTHER_INSTALLATION_ID,
        github_repo_id=_MOVED_REPO_ID,
        pr_number=_PR_BEFORE,
        merge_sha="c" * 40,
    )
    token = _mint_for(url, _NEW_INSTALLATION_ID)

    shas = [m["merge_commit_sha"] for m in
            _get(token, pr_number=_PR_BEFORE, repo=_NEW_NAME).json()["merges"]]
    assert shas == [MERGE_SHA]


def test_a_scopeless_receipt_is_refused_rather_than_widened(tmp_path, monkeypatch):
    """`_tenant_ids` returns None when neither spelling is given, and for
    every other read path that means "no tenant filter". A receipt is the one
    document that must never be assembled from rows nobody checked against a
    caller's scope, so absence raises here instead of reading everything."""
    _transferred_repo(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="installation_id or installation_ids"):
        store.receipt(None, _MOVED_REPO_ID, _PR_BEFORE)
