"""GET /v1/sessions/repositories/{id}/decisions: the Memory screen's read.

Intents pinned here:

- the listing is never gated by the three flags that gate the review-time
  read; the sentence follows all three, and only all three (ADR-0034's
  design set corrected the lock from two terms to three);
- a zero says which zero (`matched_nothing`, with where it looked);
- a broken read is a 502, never an empty list;
- the read is scoped like every session read, with the one uniform 404;
- one read per repository per TTL, so a demo burst cannot starve a review.
"""

import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from githubkit.exception import RequestFailed
from githubkit.response import Response
from test_api import _session_scope

from doug import api, intent, intent_providers, reader, store
from doug.api import app
from doug.intent import IntentDoc

ACCEPTED = IntentDoc(
    id="ADR-0001", title="Cache the thing", body="Because.", status="accepted",
    date="2026-01-02", ref="docs/decisions/ADR-0001-cache.md",
)
SUPERSEDED = IntentDoc(
    id="ADR-0002", title="Old", body="Was.", status="superseded",
    date="2026-01-03", ref="docs/decisions/ADR-0002-old.md",
)


def _report(docs, *, directory="docs/decisions", seen=None, unparseable=0, unread=0):
    return intent_providers.FetchReport(
        list(docs), directory if docs else None,
        ("docs/decisions",) if docs else intent_providers.CANDIDATE_PATHS,
        len(docs) if seen is None else seen, unparseable, unread,
    )


def _github_failure(status=500):
    raw = httpx.Response(status, request=httpx.Request("GET", "https://api.github.com/x"))
    return RequestFailed(Response(raw, dict))


@pytest.fixture
def scoped(tmp_path, monkeypatch):
    headers = _session_scope(tmp_path, monkeypatch, claim=(11,))
    api._decisions_cache_clear()
    monkeypatch.setattr(api.app_auth, "enabled", lambda: True)
    monkeypatch.setattr(api.app_auth, "installation_client", lambda installation_id: object())
    monkeypatch.delenv("DOUG_READER", raising=False)
    monkeypatch.delenv(intent.ALLOWLIST_ENV, raising=False)
    monkeypatch.delenv("DOUG_DECISIONS_TTL_SECONDS", raising=False)
    return headers


def _get(headers, repo_id=11):
    return TestClient(app).get(f"/v1/sessions/repositories/{repo_id}/decisions", headers=headers)


def test_lists_the_records_as_written_and_counts_the_accepted_ones(scoped, monkeypatch):
    calls = []
    def fetch_report(gh, owner, repo, ref=None):
        calls.append((owner, repo, ref))
        return _report([ACCEPTED, SUPERSEDED])

    monkeypatch.setattr(intent_providers, "fetch_report", fetch_report)
    response = _get(scoped)
    assert response.status_code == 200
    body = response.json()
    assert body["full_name"] == "acme/repo11"
    assert calls == [("acme", "repo11", None)]  # default-branch HEAD, as review.py reads it
    assert [item["id"] for item in body["items"]] == ["ADR-0001", "ADR-0002"]
    assert body["count_accepted"] == 1
    assert body["matched_nothing"] is False
    assert body["directory"] == "docs/decisions"
    assert body["cached"] is False


def test_the_list_is_not_gated_by_the_flags_and_the_sentence_follows_all_three(scoped, monkeypatch):
    monkeypatch.setattr(intent_providers, "fetch_report", lambda *a, **k: _report([ACCEPTED]))

    body = _get(scoped).json()
    assert body["items"], "the listing is display of the record, not the review-time read"
    assert body["reads_before_diff"] == {
        "value": False, "deep_read": True, "allowlisted": False, "reader_enabled": False,
    }

    monkeypatch.setenv("DOUG_READER", "1")
    api._decisions_cache_clear()
    body = _get(scoped).json()
    assert body["reads_before_diff"]["value"] is False
    assert body["reads_before_diff"]["reader_enabled"] is True

    monkeypatch.setenv(intent.ALLOWLIST_ENV, "101")
    api._decisions_cache_clear()
    body = _get(scoped).json()
    assert body["reads_before_diff"]["value"] is True

    # The mutation this pins: a line that followed only the allowlist and
    # deep-read would say "on" here.
    monkeypatch.delenv("DOUG_READER")
    api._decisions_cache_clear()
    assert reader.enabled() is False
    body = _get(scoped).json()
    assert body["reads_before_diff"]["value"] is False
    assert body["items"]


def test_deep_read_off_turns_the_sentence_off_and_leaves_the_list(scoped, monkeypatch):
    monkeypatch.setattr(intent_providers, "fetch_report", lambda *a, **k: _report([ACCEPTED]))
    monkeypatch.setenv("DOUG_READER", "1")
    monkeypatch.setenv(intent.ALLOWLIST_ENV, "101")
    assert store.set_repo_deep_read(101, 11, False)
    body = _get(scoped).json()
    assert body["reads_before_diff"]["deep_read"] is False
    assert body["reads_before_diff"]["value"] is False
    assert len(body["items"]) == 1


def test_a_zero_says_which_zero(scoped, monkeypatch):
    monkeypatch.setattr(intent_providers, "fetch_report", lambda *a, **k: _report([]))
    body = _get(scoped).json()
    assert body["items"] == []
    assert body["matched_nothing"] is True
    assert body["directory"] is None
    assert body["directories_searched"] == list(intent_providers.CANDIDATE_PATHS)
    assert body["count_accepted"] == 0
    assert body["binding_status"] == intent.BINDING


def test_a_broken_read_is_a_502_that_still_carries_the_sentence(scoped, monkeypatch):
    def boom(*a, **k):
        raise _github_failure(500)

    monkeypatch.setattr(intent_providers, "fetch_report", boom)
    monkeypatch.setenv("DOUG_READER", "1")
    response = _get(scoped)
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert "RequestFailed" in detail["message"]
    # The three flags need no GitHub call, so an outage does not take the
    # sentence with it (the mutation this pins: computing them after the read).
    assert detail["reads_before_diff"] == {
        "value": False, "deep_read": True, "allowlisted": False, "reader_enabled": True,
    }


def test_a_transport_error_is_a_502_too(scoped, monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectTimeout("slow")

    monkeypatch.setattr(intent_providers, "fetch_report", boom)
    assert _get(scoped).status_code == 502


def test_a_programming_error_is_not_dressed_as_a_read_failure(scoped, monkeypatch):
    """Fail loud: a bug wearing "could not be read" is a bug nobody finds."""

    def boom(*a, **k):
        raise AttributeError("no such attribute")

    monkeypatch.setattr(intent_providers, "fetch_report", boom)
    with pytest.raises(AttributeError):
        _get(scoped)


def test_an_unconfigured_github_app_is_a_503_before_any_read(scoped, monkeypatch):
    monkeypatch.setattr(api.app_auth, "enabled", lambda: False)
    calls = []
    monkeypatch.setattr(intent_providers, "fetch_report", lambda *a, **k: calls.append(1))
    response = _get(scoped)
    assert response.status_code == 503
    assert calls == []


def test_a_failure_is_held_so_an_outage_is_not_retried_on_every_navigation(scoped, monkeypatch):
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise _github_failure(503)

    monkeypatch.setattr(intent_providers, "fetch_report", boom)
    assert _get(scoped).status_code == 502
    assert _get(scoped).status_code == 502
    assert len(calls) == 1, "the held failure answers the second navigation"
    # The mutation this pins: a hold longer than the TTL. With TTL 0 the
    # hold is min(0, 30) = 0, so the next call reads again.
    monkeypatch.setenv("DOUG_DECISIONS_TTL_SECONDS", "0")
    assert _get(scoped).status_code == 502
    assert len(calls) == 2


def test_concurrent_misses_make_one_read(scoped, monkeypatch):
    calls = []
    release = threading.Event()

    def slow(*a, **k):
        calls.append(1)
        release.wait(2)
        return _report([ACCEPTED])

    monkeypatch.setattr(intent_providers, "fetch_report", slow)
    results = []

    def go():
        results.append(_get(scoped).status_code)

    threads = [threading.Thread(target=go) for _ in range(4)]
    for t in threads:
        t.start()
    time.sleep(0.2)
    release.set()
    for t in threads:
        t.join(5)
    assert results == [200, 200, 200, 200]
    assert len(calls) == 1, "four racing navigations made more than one GitHub read"


def test_the_cache_is_bounded(scoped, monkeypatch):
    for i in range(api._DECISIONS_CACHE_MAX + 5):
        api._decisions_entry((1, i), ttl=300.0)
    assert len(api._decisions_cache) <= api._DECISIONS_CACHE_MAX


def test_a_malformed_ttl_fails_loud(scoped, monkeypatch):
    monkeypatch.setattr(intent_providers, "fetch_report", lambda *a, **k: _report([ACCEPTED]))
    monkeypatch.setenv("DOUG_DECISIONS_TTL_SECONDS", "3o0")
    with pytest.raises(ValueError):
        _get(scoped)


def test_scoped_like_every_session_read_with_the_uniform_404(scoped, monkeypatch):
    monkeypatch.setattr(intent_providers, "fetch_report", lambda *a, **k: _report([ACCEPTED]))
    outside = _get(scoped, repo_id=12)  # installed, not in this user's claim
    absent = _get(scoped, repo_id=999)
    assert outside.status_code == absent.status_code == 404
    assert outside.json() == absent.json() == {"detail": "not found"}
    assert TestClient(app).get("/v1/sessions/repositories/11/decisions").status_code == 401


def test_one_read_per_repository_per_ttl(scoped, monkeypatch):
    calls = []
    monkeypatch.setattr(
        intent_providers, "fetch_report", lambda *a, **k: calls.append(1) or _report([ACCEPTED])
    )
    first = _get(scoped).json()
    second = _get(scoped).json()
    assert len(calls) == 1
    assert (first["cached"], second["cached"]) == (False, True)
    assert first["fetched_at"] == second["fetched_at"]

    # A zero TTL is "never serve from the cache", and the mutation that
    # drops the TTL check serves the stale report here.
    monkeypatch.setenv("DOUG_DECISIONS_TTL_SECONDS", "0")
    third = _get(scoped).json()
    assert len(calls) == 2
    assert third["cached"] is False
