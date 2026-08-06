import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from doug import reader, review
from doug.models import Band

PAYLOAD = {
    "risk_score": 55,
    "rationale": "Auth check moved without covering the retry path.",
    "findings": [
        {
            "category_slug": "error-handling-gap",
            "description": "Retry path skips the auth check",
            "file": "auth.py",
            "severity": "medium",
        }
    ],
}


def _pull(number=1, login="dev", user_type="User", title="Fix retry"):
    return SimpleNamespace(
        number=number,
        title=title,
        user=SimpleNamespace(login=login, type=user_type),
        additions=10,
        deletions=2,
    )


def _file(name="auth.py", status="modified", patch="+ guard()"):
    return SimpleNamespace(
        filename=name, status=status, additions=1, deletions=0, patch=patch
    )


class FakeGH:
    """Just enough of githubkit's surface for review's fetch path."""

    def __init__(self, pulls, files):
        self.rest = SimpleNamespace(
            pulls=SimpleNamespace(
                list=lambda **kw: SimpleNamespace(parsed_data=pulls),
                list_files=lambda **kw: SimpleNamespace(parsed_data=files),
            )
        )


def test_metadata_mapping_marks_bots():
    gh = FakeGH([_pull(login="renovate[bot]", user_type="Bot")], [_file()])
    items = review.fetch_open_prs(gh, "o", "r", limit=5)
    assert len(items) == 1
    pr, diff = items[0]
    assert pr.author_type.value == "agent"
    assert pr.files == ["auth.py"]
    assert "+ guard()" in diff


def test_review_uses_deterministic_when_reader_off(monkeypatch):
    monkeypatch.delenv("DOUG_READER", raising=False)
    gh = FakeGH([_pull()], [_file()])
    results = review.review_repo(gh, "o", "r", limit=5)
    assert len(results) == 1
    assert not any(x.rule.startswith("reader:") for x in results[0].verdict.reasons)


def test_review_uses_reader_when_enabled(monkeypatch):
    monkeypatch.setenv("DOUG_READER", "1")
    scopes: list[str] = []

    def fake(pr, diff, *, scope, client=None):
        scopes.append(scope)
        return reader.ReaderVerdict.model_validate(PAYLOAD)

    monkeypatch.setattr(reader, "read_diff", fake)
    gh = FakeGH([_pull()], [_file()])
    results = review.review_repo(gh, "o", "r", limit=5)
    v = results[0].verdict
    assert v.band is Band.FLAGGED
    assert v.reasons[0].rule == "reader:error-handling-gap"
    # The CLI holds no installation, so its reads charge the sentinel —
    # the same budget the other two un-tenanted callers spend from, and
    # never a customer's.
    assert scopes == [reader.SENTINEL_SCOPE]


def test_render_is_json_safe(monkeypatch):
    monkeypatch.delenv("DOUG_READER", raising=False)
    gh = FakeGH([_pull()], [_file()])
    results = review.review_repo(gh, "o", "r", limit=5)
    out = review.render(results)
    assert "Fix retry" in out
    json.dumps([r.verdict.model_dump(mode="json") for r in results])


def test_fetch_pr_records_the_head_commit():
    """head_sha is the identity /v1/review dedups repeats on; a fetch that
    dropped it would silently disable idempotency for every review."""
    from types import SimpleNamespace

    p = SimpleNamespace(
        number=7, title="Add cache",
        user=SimpleNamespace(login="dev", type="User"),
        head=SimpleNamespace(sha="c0ffee" + "0" * 34),
        html_url="https://github.com/o/r/pull/7",
        changed_files=1,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    f = SimpleNamespace(
        filename="cache.py", status="modified", additions=3, deletions=1, patch="+ x"
    )
    gh = SimpleNamespace(
        rest=SimpleNamespace(
            pulls=SimpleNamespace(
                get=lambda **kw: SimpleNamespace(parsed_data=p),
                list_files=lambda **kw: SimpleNamespace(parsed_data=[f]),
                list_reviews=lambda **kw: SimpleNamespace(parsed_data=[]),
            )
        )
    )
    meta, _diff = review.fetch_pr(gh, "o", "r", 7)
    assert meta.head_sha == "c0ffee" + "0" * 34


# --- Coverage integrity: pagination + changed_files/files_dropped --------

class PagedFakeGH:
    """list_files across N pages of 100, the shape GitHub's API actually
    paginates — a single per_page=100 call silently drops everything past
    the first page."""

    def __init__(self, pull, total_files: int, binary_names: list[str] | None = None):
        self._pull = pull
        self._total = total_files
        self._binary = binary_names or []

    def _list_files(self, **kw):
        page = kw.get("page", 1)
        per_page = kw.get("per_page", 100)
        start = (page - 1) * per_page
        end = min(start + per_page, self._total)
        files = [
            SimpleNamespace(
                filename=f"f{i}.py",
                status="modified",
                additions=1,
                deletions=0,
                patch=(None if f"f{i}.py" in self._binary else f"+ f{i}.py"),
            )
            for i in range(start, end)
        ]
        return SimpleNamespace(parsed_data=files)

    @property
    def rest(self):
        return SimpleNamespace(
            pulls=SimpleNamespace(
                get=lambda **kw: SimpleNamespace(parsed_data=self._pull),
                list=lambda **kw: SimpleNamespace(parsed_data=[self._pull]),
                list_files=self._list_files,
                list_reviews=lambda **kw: SimpleNamespace(parsed_data=[]),
            )
        )


def _pull_full(number=7, changed_files=1):
    return SimpleNamespace(
        number=number, title="Big PR",
        user=SimpleNamespace(login="dev", type="User"),
        head=SimpleNamespace(sha="c0ffee" + "0" * 34),
        html_url="https://github.com/o/r/pull/7",
        changed_files=changed_files,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_fetch_pr_paginates_past_the_first_hundred_files():
    """Today's single unpaginated call silently drops everything past file
    100 — a 250-file PR reads as a 100-file PR with no error anywhere."""
    gh = PagedFakeGH(_pull_full(changed_files=250), total_files=250)
    meta, diff = review.fetch_pr(gh, "o", "r", 7)
    assert len(meta.files) == 250
    assert diff.count("### f") == 250


def test_fetch_pr_records_changed_files_from_the_pr_object():
    gh = PagedFakeGH(_pull_full(changed_files=3), total_files=3)
    meta, _diff = review.fetch_pr(gh, "o", "r", 7)
    assert meta.changed_files == 3


def test_fetch_pr_records_files_with_no_patch_as_dropped():
    gh = PagedFakeGH(_pull_full(changed_files=3), total_files=3, binary_names=["f1.py"])
    meta, diff = review.fetch_pr(gh, "o", "r", 7)
    assert meta.files_dropped == ["f1.py"]
    assert "f1.py" not in diff  # never had a patch, never entered the diff


def test_fetch_open_prs_paginates_list_files_too():
    gh = PagedFakeGH(_pull_full(number=9), total_files=150)
    items = review.fetch_open_prs(gh, "o", "r", limit=5)
    meta, diff = items[0]
    assert len(meta.files) == 150
    assert diff.count("### f") == 150


def test_fetch_open_prs_derives_changed_files_from_the_paginated_count():
    """pulls.list returns PullRequestSimple, which has no changed_files
    field at all — the paginated file count is the only source here."""
    gh = PagedFakeGH(_pull_full(number=9), total_files=150)
    items = review.fetch_open_prs(gh, "o", "r", limit=5)
    meta, _diff = items[0]
    assert meta.changed_files == 150


# --- Live review state (approvals no longer hardcoded 0) -----------------

def _review(login, state, submitted_at):
    return SimpleNamespace(
        user=SimpleNamespace(login=login, type="User"), state=state, submitted_at=submitted_at
    )


def _pull_with_reviews(reviews, created_at):
    p = _pull_full(changed_files=1)
    p.created_at = created_at
    return p, reviews


class ReviewedFakeGH:
    def __init__(self, pull, files, reviews):
        self._pull, self._files, self._reviews = pull, files, reviews

    @property
    def rest(self):
        return SimpleNamespace(
            pulls=SimpleNamespace(
                get=lambda **kw: SimpleNamespace(parsed_data=self._pull),
                list_files=lambda **kw: SimpleNamespace(
                    parsed_data=(self._files if kw.get("page", 1) == 1 else [])
                ),
                list_reviews=lambda **kw: SimpleNamespace(parsed_data=self._reviews),
            )
        )


def test_fetch_pr_counts_current_approvals_by_distinct_reviewer():
    """A reviewer who re-approves after a push must not double-count — the
    rubber-stamp rule reads approvals == 1 as 'exactly one reviewer signed
    off', not 'one approval event'."""
    opened = datetime(2026, 1, 1, tzinfo=UTC)
    p, reviews = _pull_with_reviews(
        [
            _review("alice", "APPROVED", opened + timedelta(minutes=3)),
            _review("alice", "APPROVED", opened + timedelta(minutes=10)),  # re-approval
        ],
        opened,
    )
    gh = ReviewedFakeGH(p, [_file()], reviews)
    meta, _diff = review.fetch_pr(gh, "o", "r", 7)
    assert meta.approvals == 1


def test_fetch_pr_uses_a_reviewers_latest_state_not_their_first():
    """approve, then a maintainer re-requests changes on the same PR: the
    reviewer's CURRENT stance is changes-requested, not approved."""
    opened = datetime(2026, 1, 1, tzinfo=UTC)
    p, reviews = _pull_with_reviews(
        [
            _review("alice", "APPROVED", opened + timedelta(minutes=3)),
            _review("alice", "CHANGES_REQUESTED", opened + timedelta(minutes=20)),
        ],
        opened,
    )
    gh = ReviewedFakeGH(p, [_file()], reviews)
    meta, _diff = review.fetch_pr(gh, "o", "r", 7)
    assert meta.approvals == 0


def test_fetch_pr_computes_latency_to_the_first_approval():
    opened = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    p, reviews = _pull_with_reviews(
        [_review("alice", "APPROVED", opened + timedelta(minutes=4))], opened
    )
    gh = ReviewedFakeGH(p, [_file()], reviews)
    meta, _diff = review.fetch_pr(gh, "o", "r", 7)
    assert meta.approval_latency_s == 240.0


def test_fetch_pr_reports_no_latency_without_an_approval():
    opened = datetime(2026, 1, 1, tzinfo=UTC)
    p, reviews = _pull_with_reviews(
        [_review("alice", "COMMENTED", opened + timedelta(minutes=4))], opened
    )
    gh = ReviewedFakeGH(p, [_file()], reviews)
    meta, _diff = review.fetch_pr(gh, "o", "r", 7)
    assert meta.approvals == 0
    assert meta.approval_latency_s is None


def test_list_all_files_stops_at_githubs_own_file_cap():
    """GitHub caps list_files at 3000 files per PR — a client that keeps
    asking past that gets more full pages back from nothing real (a
    misbehaving mock, or a client bug), so the loop needs its own bound
    rather than trusting a short page to eventually arrive."""

    class InfiniteFakeGH:
        @property
        def rest(self):
            return SimpleNamespace(
                pulls=SimpleNamespace(
                    list_files=lambda **kw: SimpleNamespace(
                        parsed_data=[_file(name=f"f{i}.py") for i in range(100)]
                    )
                )
            )

    files = review._list_all_files(InfiniteFakeGH(), "o", "r", 7)
    assert len(files) == 3000


# --- Coverage integrity: binary files are not "dropped" -------------------

def _binary_file(name="logo.png"):
    """GitHub reports a genuinely binary file with no patch AND no
    line-level stats — it cannot count lines in a binary, unlike a large
    text file it merely declines to inline."""
    return SimpleNamespace(filename=name, status="added", additions=0, deletions=0, patch=None)


def _oversized_text_file(name="generated.go"):
    """A large text file GitHub computed real stats for but omitted the
    patch text — this one IS reviewable content that never arrived."""
    return SimpleNamespace(
        filename=name, status="modified", additions=4000, deletions=200, patch=None
    )


def test_fetch_pr_does_not_count_a_genuine_binary_as_dropped():
    """A screenshot or a compiled asset never had reviewable content to
    miss — flagging every PR that touches one as an incomplete read would
    make the signal common enough to ignore, exactly the overclaim this
    field exists to prevent in the other direction."""
    p = _pull_full(changed_files=2)
    p.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    gh = ReviewedFakeGH(p, [_file(), _binary_file()], [])
    meta, _diff = review.fetch_pr(gh, "o", "r", 7)
    assert meta.files_dropped == []


def test_fetch_pr_still_counts_an_oversized_text_file_as_dropped():
    """GitHub reporting real additions/deletions with no patch means it
    computed a diff and withheld the text — content that should have
    been reviewable and was not. Coverage.complete must still catch this."""
    p = _pull_full(changed_files=2)
    p.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    gh = ReviewedFakeGH(p, [_file(), _oversized_text_file()], [])
    meta, _diff = review.fetch_pr(gh, "o", "r", 7)
    assert meta.files_dropped == ["generated.go"]


def test_fetch_pr_degrades_gracefully_when_review_state_is_unreadable():
    """A malformed review payload (mixed tz-aware/naive timestamps, or any
    other surprise in list_reviews) must cost the approvals signal, not
    the entire PR fetch — files and diff are the load-bearing return
    value, and review state is one input among several deterministic
    rules use."""
    p = _pull_full(changed_files=1)
    p.created_at = datetime(2026, 1, 1)  # naive — TypeError vs an aware submitted_at

    class BrokenReviewsGH(ReviewedFakeGH):
        @property
        def rest(self):
            r = super().rest
            r.pulls.list_reviews = lambda **kw: SimpleNamespace(
                parsed_data=[_review("alice", "APPROVED", datetime(2026, 1, 1, tzinfo=UTC))]
            )
            return r

    gh = BrokenReviewsGH(p, [_file()], [])
    meta, diff = review.fetch_pr(gh, "o", "r", 7)
    assert meta.approvals == 0
    assert meta.approval_latency_s is None
    assert diff  # the actually load-bearing part still worked


def _f(filename: str, patch_len: int, status: str = "modified"):
    """A GitHub file object as far as read_order cares: .filename + .patch."""
    return SimpleNamespace(
        filename=filename,
        status=status,
        additions=1,
        deletions=0,
        patch="x" * patch_len,
    )


def test_read_order_puts_code_before_tests_before_prose():
    """DIFF_BUDGET cuts the assembled diff linearly, so whatever sorts last
    is what the reader never sees. Prose last is the single biggest win:
    across 30 first-parent commits, 37% of diffs truncated but only 20% had
    CODE over budget — the gap was docs and tests crowding out code."""
    files = [
        _f("docs/ROADMAP.md", 100),
        _f("api/tests/test_tenancy.py", 100),
        _f("api/doug/tenancy.py", 100),
    ]
    assert [f.filename for f in review.read_order(files)] == [
        "api/doug/tenancy.py",
        "api/tests/test_tenancy.py",
        "docs/ROADMAP.md",
    ]


def test_read_order_sends_smallest_first_within_a_tier():
    """Smallest-first maximises how many files arrive WHOLE, which is what
    lets the reader reason correctly rather than half-correctly. The cost —
    the biggest file in a tier is likeliest to be dropped — is paid visibly
    via coverage.files_unseen, not silently."""
    files = [_f("big.py", 900), _f("small.py", 100), _f("mid.py", 500)]
    assert [f.filename for f in review.read_order(files)] == [
        "small.py",
        "mid.py",
        "big.py",
    ]


def test_read_order_is_deterministic_for_equal_keys():
    """Two files of identical tier and size must not swap between runs.
    A nondeterministic order makes the same head_sha produce different
    reads, which would make verdicts unreproducible and quietly break the
    idempotency pre-read's assumption that a re-run sees the same input."""
    files = [_f("b.py", 100), _f("a.py", 100), _f("c.py", 100)]
    once = [f.filename for f in review.read_order(files)]
    twice = [f.filename for f in review.read_order(list(files))]
    assert once == twice == ["b.py", "a.py", "c.py"]  # input order preserved


def test_read_order_tolerates_files_with_no_patch():
    """GitHub returns binaries and too-large-to-inline files with
    patch=None. They are filtered out at the join, but read_order sees them
    first and must not raise on len(None)."""
    files = [_f("a.py", 100), SimpleNamespace(filename="logo.png", patch=None)]
    assert len(review.read_order(files)) == 2


def _tier_ordered_diff(files):
    """Synthetic tiered diff for reader coverage invariants.

    Caller-level ordering regressions below exercise fetch_pr and
    fetch_open_prs directly, so this helper deliberately stays limited to
    coverage's pure input/output contract.
    """
    return reader.CHUNK_SEPARATOR.join(
        reader.diff_chunk(f.filename, f.status, f.additions, f.deletions, f.patch)
        for f in review.read_order(files)
        if f.patch
    )


def _pr50_files():
    """Representative PR #50 (41182c1) slice at real per-file sizes.

    It retains the motivating code/test/docs shape for this regression
    without claiming to reproduce all 18 files or 275,858 characters.
    """
    return [
        _f("api/deploy/gcp.sh", 2126),
        _f("api/doug/api.py", 18606),
        _f("api/doug/check_run.py", 1158),
        _f("api/doug/keyformat.py", 2812),
        _f("api/doug/migrations.py", 3341),
        _f("api/doug/store.py", 15404),
        _f("api/doug/tenancy.py", 13014),
        _f("api/tests/test_api.py", 39769),
        _f("docs/superpowers/plans/2026-08-04-tenant-api-keys.md", 105749),
    ]


class PR50FakeGH:
    """The GitHub boundary needed to return PR #50's real file ordering."""

    def __init__(self, pull, files):
        self._pull = pull
        self._files = files

    @property
    def rest(self):
        return SimpleNamespace(
            pulls=SimpleNamespace(
                get=lambda **kw: SimpleNamespace(parsed_data=self._pull),
                list=lambda **kw: SimpleNamespace(parsed_data=[self._pull]),
                list_files=lambda **kw: SimpleNamespace(
                    parsed_data=(self._files if kw.get("page", 1) == 1 else [])
                ),
                list_reviews=lambda **kw: SimpleNamespace(parsed_data=[]),
            )
        )


def _pr50_gh():
    return PR50FakeGH(_pull_full(changed_files=9), _pr50_files())


def test_pr50_fetch_pr_reads_tenancy_at_the_old_budget(monkeypatch):
    """The regression, pinned at the OLD 30k budget so it tests the
    ORDERING alone and stays meaningful independent of Task 4.

    Three consecutive reviews of the tenancy work never read tenancy.py:
    api.py (18,606 chars) ate 62% of the budget purely because 'a' sorts
    before 't'. After tiering, the 13,014-char tenancy.py is sent whole and
    api.py is the one named as unseen."""
    monkeypatch.setattr(reader, "DIFF_BUDGET", 30_000)
    _meta, diff = review.fetch_pr(_pr50_gh(), "o", "r", 7)
    cov = reader.coverage(diff)

    assert "api/doug/tenancy.py" not in cov.files_unseen
    assert "api/doug/api.py" in cov.files_unseen


def test_pr50_fetch_open_prs_reads_tenancy_at_the_old_budget(monkeypatch):
    """Both call sites build their own diff string, so each must protect
    tenancy.py from a top-of-list api.py crowding it out at 30k."""
    monkeypatch.setattr(reader, "DIFF_BUDGET", 30_000)
    items = review.fetch_open_prs(_pr50_gh(), "o", "r", limit=1)
    cov = reader.coverage(items[0][1])

    assert "api/doug/tenancy.py" not in cov.files_unseen
    assert "api/doug/api.py" in cov.files_unseen


def test_pr50_reads_every_code_file_at_the_shipped_budget():
    """At 100k the ordering plus the raised ceiling send all 57,441 chars
    of PR #50's code. Docs still rank last and are cut partway through —
    that is the design, not a gap."""
    cov = reader.coverage(_tier_ordered_diff(_pr50_files()))

    for code_file in (
        "api/doug/tenancy.py",
        "api/doug/api.py",
        "api/doug/store.py",
        "api/doug/keyformat.py",
        "api/doug/migrations.py",
        "api/doug/check_run.py",
        "api/deploy/gcp.sh",
    ):
        assert code_file not in cov.files_unseen, code_file

    docs_path = "docs/superpowers/plans/2026-08-04-tenant-api-keys.md"
    assert docs_path not in cov.files_unseen
    assert cov.file_cut == docs_path


def test_reordering_keeps_coverage_honest(monkeypatch):
    """The invariant reader.py's coverage block exists to protect: a
    partial read must never look like a complete one. Reordering changes
    WHICH files are dropped, so it must not change whether the drop is
    reported — every unsent file still appears in files_unseen, and
    complete stays False."""
    monkeypatch.setattr(reader, "DIFF_BUDGET", 5_000)
    cov = reader.coverage(_tier_ordered_diff(_pr50_files()))

    assert not cov.complete
    assert len(cov.files_unseen) > 0
    sent = {f.filename for f in _pr50_files()} - set(cov.files_unseen)
    assert sent, "at least one file should have been sent"
    assert len(cov.files_unseen) + len(sent) == 9


def test_ordering_is_a_noop_below_the_budget():
    """A PR that fits sends every file no matter how it is ordered. This
    guards against a tiering bug that silently drops a file even when
    there was room for it."""
    files = [_f("docs/a.md", 50), _f("b.py", 50), _f("tests/test_c.py", 50)]
    cov = reader.coverage(_tier_ordered_diff(files))

    assert cov.complete
    assert cov.files_unseen == []
    assert cov.files_sent == 3
