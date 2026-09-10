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

import pytest
from fastapi.testclient import TestClient
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


def _report(docs, *, directory="docs/decisions", seen=None, skipped=0):
    return intent_providers.FetchReport(
        list(docs), directory if docs else None,
        ("docs/decisions",) if docs else intent_providers.CANDIDATE_PATHS,
        len(docs) if seen is None else seen, skipped,
    )


@pytest.fixture
def scoped(tmp_path, monkeypatch):
    headers = _session_scope(tmp_path, monkeypatch, claim=(11,))
    api._decisions_cache_clear()
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


def test_a_broken_read_is_a_502_never_an_empty_list(scoped, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("rate limited")

    monkeypatch.setattr(intent_providers, "fetch_report", boom)
    response = _get(scoped)
    assert response.status_code == 502
    assert "RuntimeError" in response.json()["detail"]


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
