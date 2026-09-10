"""The fetch report tells three zeros apart, and `fetch` is unchanged by it.

Intent: a bare "0 decisions" beside a real review count reads as "Doug found
nothing worth remembering" when the records may live somewhere Doug did not
look. The report carries where it looked and what it skipped so the Memory
screen can say which zero it is (design set, O3). The review path keeps
reading `fetch()`, which is the report's `docs` and nothing else.
"""

from types import SimpleNamespace

import httpx
import pytest
from githubkit.exception import RequestFailed
from githubkit.response import Response

from doug import intent_providers

RECORD = """---
title: Cache the thing
status: accepted
date: 2026-01-02
---

## Context
Because.
"""
SUPERSEDED = RECORD.replace("status: accepted", "status: superseded")
NOT_A_RECORD = "# A README in the decisions directory\n"


def _missing(path: str) -> RequestFailed:
    raw = httpx.Response(
        404, request=httpx.Request("GET", f"https://api.github.com/repos/o/r/contents/{path}")
    )
    return RequestFailed(Response(raw, dict))


class _Contents:
    """A stub of `gh.rest.repos.get_content` over a dict of directories."""

    def __init__(self, tree: dict[str, dict[str, str]], *, fail: Exception | None = None):
        self.tree = tree
        self.fail = fail
        self.calls: list[str] = []

    def get_content(self, *, owner, repo, path, **_):
        self.calls.append(path)
        if self.fail is not None:
            raise self.fail
        for directory, files in self.tree.items():
            if path == directory:
                listing = [
                    SimpleNamespace(name=name, type="file", path=f"{directory}/{name}")
                    for name in files
                ]
                return SimpleNamespace(parsed_data=listing)
            if path.startswith(directory + "/"):
                name = path[len(directory) + 1 :]
                if name in files:
                    return SimpleNamespace(
                        parsed_data=SimpleNamespace(content=files[name], encoding="")
                    )
        raise _missing(path)


def _gh(tree, **kw):
    contents = _Contents(tree, **kw)
    return SimpleNamespace(rest=SimpleNamespace(repos=contents)), contents


def test_the_first_directory_that_yields_records_wins_and_the_report_says_which(monkeypatch):
    monkeypatch.delenv("DOUG_ADR_PATH", raising=False)
    gh, contents = _gh(
        {
            "docs/adr": {"ADR-0001-cache.md": RECORD, "README.md": NOT_A_RECORD},
            "doc/adr": {"ADR-0009-other.md": RECORD},
        }
    )
    report = intent_providers.fetch_report(gh, "o", "r")
    assert [d.id for d in report.docs] == ["ADR-0001"]
    assert report.directory == "docs/adr"
    assert report.searched == ("docs/decisions", "docs/adr")
    assert (report.files_seen, report.files_skipped) == (2, 1)
    assert report.matched_nothing is False
    # The review path reads exactly the report's records.
    assert [d.id for d in intent_providers.fetch(gh, "o", "r")] == ["ADR-0001"]


def test_no_candidate_directory_is_a_zero_that_names_where_it_looked(monkeypatch):
    monkeypatch.delenv("DOUG_ADR_PATH", raising=False)
    gh, contents = _gh({})
    report = intent_providers.fetch_report(gh, "o", "r")
    assert report.matched_nothing is True
    assert report.directory is None
    assert report.searched == intent_providers.CANDIDATE_PATHS
    assert (report.files_seen, report.files_skipped) == (0, 0)
    assert intent_providers.fetch(gh, "o", "r") == []


def test_a_directory_of_unparseable_files_is_a_different_zero(monkeypatch):
    """The mutation this pins: collapse the report to `docs` alone and the
    two zeros above become one."""
    monkeypatch.delenv("DOUG_ADR_PATH", raising=False)
    gh, _ = _gh({"docs/decisions": {"README.md": NOT_A_RECORD, "template.md": "no frontmatter"}})
    report = intent_providers.fetch_report(gh, "o", "r")
    assert report.matched_nothing is True
    assert report.directory is None
    assert (report.files_seen, report.files_skipped) == (2, 2)


def test_a_superseded_record_is_listed_and_left_to_the_caller_to_filter(monkeypatch):
    monkeypatch.delenv("DOUG_ADR_PATH", raising=False)
    gh, _ = _gh({"docs/decisions": {"ADR-0002-old.md": SUPERSEDED}})
    report = intent_providers.fetch_report(gh, "o", "r")
    assert [d.status for d in report.docs] == ["superseded"]


def test_a_transport_failure_is_raised_not_reported_as_nothing(monkeypatch):
    monkeypatch.delenv("DOUG_ADR_PATH", raising=False)
    gh, _ = _gh({}, fail=RuntimeError("rate limited"))
    with pytest.raises(RuntimeError):
        intent_providers.fetch_report(gh, "o", "r")
