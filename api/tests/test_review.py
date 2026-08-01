import json
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
    fake = lambda pr, diff, client=None: reader.ReaderVerdict.model_validate(PAYLOAD)  # noqa: E731
    monkeypatch.setattr(reader, "read_diff", fake)
    gh = FakeGH([_pull()], [_file()])
    results = review.review_repo(gh, "o", "r", limit=5)
    v = results[0].verdict
    assert v.band is Band.FLAGGED
    assert v.reasons[0].rule == "reader:error-handling-gap"


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
    )
    f = SimpleNamespace(
        filename="cache.py", status="modified", additions=3, deletions=1, patch="+ x"
    )
    gh = SimpleNamespace(
        rest=SimpleNamespace(
            pulls=SimpleNamespace(
                get=lambda **kw: SimpleNamespace(parsed_data=p),
                list_files=lambda **kw: SimpleNamespace(parsed_data=[f]),
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
            )
        )


def _pull_full(number=7, changed_files=1):
    return SimpleNamespace(
        number=number, title="Big PR",
        user=SimpleNamespace(login="dev", type="User"),
        head=SimpleNamespace(sha="c0ffee" + "0" * 34),
        html_url="https://github.com/o/r/pull/7",
        changed_files=changed_files,
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
