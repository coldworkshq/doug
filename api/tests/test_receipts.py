"""The governing-verdict rule — pre-registration §2.1, as SQL'd in §2.2.

These tests guard the one selection rule that BOTH a customer's receipt and
the published quarterly miss rate run. The whole claim of the outcome loop is
that those two numbers come from the same ledger under the same definition,
so a divergence here is not a bug in a helper, it is the product's central
claim failing quietly.
"""

import itertools
import pathlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select, text

from doug import store

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
