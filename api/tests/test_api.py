import hashlib
import hmac

import pytest
from fastapi.testclient import TestClient

from doug.api import app

client = TestClient(app)


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_score_endpoint():
    r = client.post(
        "/v1/score",
        json={
            "number": 1,
            "title": "bump dep",
            "author": "bot[bot]",
            "files": ["package.json", "package-lock.json"],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["band"] in ("cleared", "flagged")
    assert body["reasons"]


def test_queue_refuses_without_a_token(monkeypatch):
    monkeypatch.setenv("DOUG_API_TOKEN", "t0ken")
    r = client.get("/v1/queue")
    assert r.status_code == 401


def test_queue_refuses_when_token_unconfigured(monkeypatch):
    monkeypatch.delenv("DOUG_API_TOKEN", raising=False)
    r = client.get("/v1/queue", headers={"X-Doug-Token": "anything"})
    assert r.status_code == 503


def test_queue_summary_is_consistent(monkeypatch):
    monkeypatch.setenv("DOUG_API_TOKEN", "t0ken")
    r = client.get("/v1/queue", headers={"X-Doug-Token": "t0ken"})
    assert r.status_code == 200
    body = r.json()
    s = body["summary"]
    assert s["open"] == len(body["items"])
    assert s["flagged"] + s["cleared"] == s["open"]
    # Items arrive sorted by score, riskiest first.
    scores = [i["verdict"]["score"] for i in body["items"]]
    assert scores == sorted(scores, reverse=True)
    # The known-risky fixture (auth + migration) is flagged and on top.
    assert body["items"][0]["pr"]["number"] == 9612
    assert body["items"][0]["verdict"]["band"] == "flagged"


def _sig(secret: bytes, body: bytes, algo: str) -> str:
    digest = hashlib.sha256 if algo == "sha256" else hashlib.sha1
    return f"{algo}=" + hmac.new(secret, body, digest).hexdigest()


def test_webhook_refuses_when_secret_unconfigured(monkeypatch):
    # An unconfigured deployment must not accept unverified payloads: under
    # the App a webhook triggers a paid model read.
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    r = client.post("/webhooks/github", content=b"{}")
    assert r.status_code == 503


def test_webhook_refuses_signed_body_when_secret_unconfigured(monkeypatch):
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    r = client.post(
        "/webhooks/github",
        content=b"{}",
        headers={"X-Hub-Signature-256": "sha256=deadbeef"},
    )
    assert r.status_code == 503


def test_webhook_rejects_sha1_digest_on_the_256_header(monkeypatch):
    # githubkit picks the digest from the prefix, not the header name, so an
    # attacker-chosen "sha1=" would silently weaken verification.
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "s3cret")
    body = b'{"zen":"x"}'
    r = client.post(
        "/webhooks/github",
        content=body,
        headers={"X-Hub-Signature-256": _sig(b"s3cret", body, "sha1")},
    )
    assert r.status_code == 401


def test_webhook_accepts_a_valid_sha256_signature(monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "s3cret")
    body = b'{"zen":"x"}'
    r = client.post(
        "/webhooks/github",
        content=body,
        headers={"X-Hub-Signature-256": _sig(b"s3cret", body, "sha256")},
    )
    assert r.status_code == 202


def test_startup_refuses_to_run_without_a_webhook_secret(monkeypatch):
    """GITHUB_WEBHOOK_SECRET was set out-of-band in production and the
    current deploy() wipes it. A service that boots without it looks
    perfectly healthy while every delivery it accepts is unverifiable —
    and under the App, an accepted delivery is a paid model read that
    anyone who can POST gets to trigger. Refusing at startup is the only
    version of this that shows up in a deploy instead of a bill.

    Note: this only fires when the client is entered as a context manager,
    which is why the module-level `client` above keeps working."""
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="GITHUB_WEBHOOK_SECRET"):
        with TestClient(app):
            pass


def test_startup_succeeds_once_the_secret_is_configured(monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "s3cret")
    with TestClient(app) as c:
        assert c.get("/healthz").status_code == 200


def test_webhook_rejects_a_delivery_with_no_signature_at_all(monkeypatch):
    """The wrong-digest case is covered above; this is the shape an
    attacker sends first, and nothing covered it."""
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "s3cret")
    r = client.post(
        "/webhooks/github", content=b'{"zen":"x"}', headers={"X-GitHub-Event": "ping"}
    )
    assert r.status_code == 401
