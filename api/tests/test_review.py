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
