import base64
import hashlib
import hmac
import inspect
import json
import threading
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from doug import (
    api,
    app_auth,
    entitlements,
    ingest,
    install_flow,
    outcome_queue,
    session_auth,
    store,
    tenancy,
    worker,
    workos_client,
)
from doug.api import app
from doug.models import Band, JobItem, Reason, Verdict

client = TestClient(app)

VERDICT_FOR_QUEUE = Verdict(
    score=0.62,
    band=Band.FLAGGED,
    threshold=0.30,
    reasons=[Reason(rule="reader:race-condition", label="Unguarded write", weight=0.0)],
)
PR_META = {"number": 1, "title": "Add cache", "author": "dev", "files": ["cache.py"]}


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
    """deploy() does set GITHUB_WEBHOOK_SECRET — it has been in
    --set-secrets since #14 — so this is not defending against the CI path.
    It defends against every other way a revision can come up without it: a
    hand-deployed revision, a new project with no Secret Manager entry, a
    local run. A service that boots without it looks perfectly healthy while
    every delivery it accepts is unverifiable — and under the App, an
    accepted delivery is a paid model read that anyone who can POST gets to
    trigger. Refusing at startup is the only version of this that shows up
    in a deploy instead of a bill.

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


# The startup catch-up sweep. Both of its guards are off under the ordinary
# test environment (no App credentials, no DATABASE_URL), so the tests below
# patch the two predicates rather than the environment behind them: what is
# under test is the lifespan's decision, not app_auth's and store's own
# reading of the environment, which their own tests cover. Leaving it at "the
# guards are off in tests" is what left the thread, the guards and the
# exception handler with no coverage at all.


def _startup_guards(monkeypatch, *, app_enabled: bool, ledger: bool) -> None:
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setattr(app_auth, "enabled", lambda: app_enabled)
    monkeypatch.setattr(store, "enabled", lambda: ledger)


def _startup_threads() -> list[threading.Thread]:
    """The live sweep threads, found by the name the lifespan gives them.

    Thread.start() registers the thread before it returns, and the lifespan
    starts it before it yields, so by the time TestClient.__enter__ hands
    control back an expected thread is always here — which is what makes
    "no thread was started" a real assertion rather than a race."""
    return [t for t in threading.enumerate() if t.name == api.STARTUP_THREAD_NAME]


def _join_startup_threads(timeout: float = 5.0) -> None:
    for t in _startup_threads():
        t.join(timeout)
        assert not t.is_alive(), "the startup reconcile thread never finished"


def test_startup_reconciles_the_backlog_before_it_drains_it(monkeypatch):
    """Order is the whole behavior: draining first drains an empty queue.

    reconcile_all only enqueues. A drain that runs ahead of it claims
    whatever the last delivery happened to leave behind and stops, so every
    row this sweep is about to discover then waits for some unrelated
    delivery to kick a drain — which on the quiet repo whose missed
    deliveries stranded them is the case this exists for.
    """
    calls: list[str] = []
    drained = threading.Event()

    def fake_reconcile() -> int:
        calls.append("reconcile")
        return 3

    def fake_drain() -> int:
        calls.append("drain")
        drained.set()
        return 0

    monkeypatch.setattr(worker, "reconcile_all", fake_reconcile)
    monkeypatch.setattr(worker, "drain", fake_drain)
    _startup_guards(monkeypatch, app_enabled=True, ledger=True)

    with TestClient(app):
        # An Event the fake sets, not a sleep: the thread is asynchronous to
        # this test by construction, and a fixed pause would be either flaky
        # or slow and would still prove nothing about the ordering.
        assert drained.wait(timeout=5), "startup never reached the drain"
    _join_startup_threads()
    assert calls == ["reconcile", "drain"]


def test_startup_serves_before_the_reconcile_it_started_finishes(monkeypatch):
    """A thread, not an await and not an inline call.

    Cloud Run holds a revision out of rotation until the lifespan yields,
    and this sweep walks every open PR of every installation and then pays
    for model reads on what it queued. Inline, the revision fails its
    health check and never serves at all — so "the lifespan yields while the
    sweep is still running" is the property, not an implementation detail.
    """
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def slow_reconcile() -> int:
        entered.set()
        release.wait(timeout=5)
        finished.set()
        return 0

    monkeypatch.setattr(worker, "reconcile_all", slow_reconcile)
    monkeypatch.setattr(worker, "drain", lambda: 0)
    _startup_guards(monkeypatch, app_enabled=True, ledger=True)

    try:
        with TestClient(app) as c:
            assert entered.wait(timeout=5), "the sweep never ran"
            assert not finished.is_set(), "startup blocked until the sweep finished"
            assert c.get("/healthz").status_code == 200
    finally:
        release.set()
        _join_startup_threads()


@pytest.mark.parametrize(
    ("app_enabled", "ledger"),
    [(False, True), (True, False)],
)
def test_startup_starts_no_sweep_when_either_half_is_missing(monkeypatch, app_enabled, ledger):
    """No App credentials, or no ledger, and nothing starts at all.

    Both halves are needed for the sweep to do anything: without the App it
    has no client to list PRs with, without the ledger it has no
    installations to list and nowhere to enqueue. Getting this wrong is not
    a no-op — it is every ledger-less local run and this test suite itself
    spawning a thread that talks to GitHub on import.
    """
    calls: list[str] = []
    release = threading.Event()

    def fake_reconcile() -> int:
        calls.append("reconcile")
        # Blocks, so a thread that should never have existed is still alive
        # — and so still enumerable — when the assertion below looks for it.
        # Without this it could finish and deregister first, and the
        # assertion would pass on the code it exists to catch.
        release.wait(timeout=5)
        return 0

    monkeypatch.setattr(worker, "reconcile_all", fake_reconcile)
    monkeypatch.setattr(worker, "drain", lambda: calls.append("drain"))
    _startup_guards(monkeypatch, app_enabled=app_enabled, ledger=ledger)

    try:
        with TestClient(app) as c:
            assert _startup_threads() == []
            assert c.get("/healthz").status_code == 200
        assert calls == []
    finally:
        release.set()
        _join_startup_threads()


def test_a_failing_startup_reconcile_neither_escapes_nor_reaches_the_drain(monkeypatch, capsys):
    """Catch-up is best-effort: a sweep that raises must cost only itself.

    GitHub being down, an installation token that will not mint, a ledger
    that refuses the first connection — all of them land here, and none of
    them is a reason for this revision to stop serving /v1/score. The drain
    must not run either: reconcile_all raising means the queue was never
    healed, so there is nothing this pass discovered to drain.
    """
    calls: list[str] = []
    escaped: list = []
    raised = threading.Event()

    def boom() -> int:
        raised.set()
        raise RuntimeError("github said no")

    # threading.excepthook is what a thread's uncaught exception reaches, so
    # recording it is the direct test of "the except is there" — an assertion
    # about the log line alone would still pass if the exception escaped.
    monkeypatch.setattr(threading, "excepthook", lambda args: escaped.append(args))
    monkeypatch.setattr(worker, "reconcile_all", boom)
    monkeypatch.setattr(worker, "drain", lambda: calls.append("drain"))
    _startup_guards(monkeypatch, app_enabled=True, ledger=True)

    with TestClient(app) as c:
        assert raised.wait(timeout=5), "the sweep never ran"
        _join_startup_threads()
        assert c.get("/healthz").status_code == 200
    assert escaped == [], "the sweep's failure escaped its thread"
    assert calls == [], "the drain ran behind a reconcile that failed"
    assert "startup reconcile failed (RuntimeError: github said no)" in capsys.readouterr().err


def test_startup_warns_when_verdicts_reference_installations_the_ledger_lacks(
    tmp_path, monkeypatch, capsys
):
    """REVIEWING.md § 'A table only a webhook populates': prod sat for weeks
    with 33 verdicts and ZERO installations rows, and reconcile_all was a
    silent structural no-op. The next MT0-class state must be a loud line,
    not a quiet nothing."""
    _api_db(tmp_path, monkeypatch)
    _seed_verdict(repo="drewjst/a", github_repo_id=111, installation_id=150424894, pr_number=1)
    monkeypatch.setattr(worker, "reconcile_all", lambda: 0)
    monkeypatch.setattr(worker, "drain", lambda: None)
    from doug.api import _startup_reconcile

    _startup_reconcile()
    err = capsys.readouterr().err
    assert "DRIFT" in err and "installation webhook" in err and "MT0" in err


def test_startup_warns_when_verdicts_reference_repos_the_ledger_lacks(
    tmp_path, monkeypatch, capsys
):
    """The per-repo sibling of the case above. Task 10 made tenant queue
    reads join through installation_repos by (installation_id,
    github_repo_id), so a repo whose repositories_added delivery never
    arrived is now invisible to its own tenant's queue while the operator's
    unscoped queue (installation_id alone) still shows it — a second
    MT0-class drift mode the empty-ledger check above cannot see, because
    the installations row for this tenant DOES exist here."""
    _api_db(tmp_path, monkeypatch)
    store.upsert_installation(150424894, "drewjst", "User", "active")
    _seed_verdict(repo="drewjst/gone", github_repo_id=333, installation_id=150424894, pr_number=1)
    monkeypatch.setattr(worker, "reconcile_all", lambda: 0)
    monkeypatch.setattr(worker, "drain", lambda: None)
    from doug.api import _startup_reconcile

    _startup_reconcile()
    err = capsys.readouterr().err
    assert "DRIFT" in err and "installation_repos" in err and "MT0" in err


def test_a_failing_drift_check_never_blocks_the_catchup_sweep(
    tmp_path, monkeypatch, capsys
):
    """Doug's own review of PR #50 (startup-error-path): the drift
    diagnostics shared one try with the sweep, so a diagnostic-only DB error
    skipped reconcile_all for the whole cold start — the exact silent-no-op
    class the diagnostics exist to prevent. They are advisory; the sweep is
    the job."""
    _api_db(tmp_path, monkeypatch)
    ran = []
    monkeypatch.setattr(worker, "reconcile_all", lambda: ran.append(True) or 0)
    monkeypatch.setattr(worker, "drain", lambda: None)

    def _boom():
        raise RuntimeError("diagnostic db hiccup")

    monkeypatch.setattr(store, "count_verdict_repos_missing_from_ledger", _boom)
    from doug.api import _startup_reconcile

    _startup_reconcile()
    assert ran, "the sweep must run even when a drift diagnostic fails"
    err = capsys.readouterr().err
    assert "drift check failed" in err and "diagnostic db hiccup" in err


def test_webhook_rejects_a_delivery_with_no_signature_at_all(monkeypatch):
    """The wrong-digest case is covered above; this is the shape an
    attacker sends first, and nothing covered it."""
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "s3cret")
    r = client.post(
        "/webhooks/github", content=b'{"zen":"x"}', headers={"X-GitHub-Event": "ping"}
    )
    assert r.status_code == 401


SECRET = "s3cret"
INSTALLATION = {"id": 150424894, "account": {"login": "drewjst", "type": "User"}}


def _hook_env(tmp_path, monkeypatch) -> list:
    """Configure the webhook and cut the two background kicks.

    The kicks must be cut, not tolerated: TestClient waits for background
    tasks, so a real worker.drain would claim the job these tests just
    asserted on and run it against a monkeypatch-free pipeline."""
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/doug.db")
    # Materialise the schema here rather than leaving it to whichever
    # request happens to write first. The tests that assert a delivery
    # wrote NOTHING (401s, ignored events, drafts, forks) never reach a
    # write, so without this _table() opens an empty sqlite file and the
    # assertion dies on "no such table" instead of passing.
    assert store.enabled()
    kicks: list = []
    monkeypatch.setattr(worker, "drain", lambda *a, **k: kicks.append("drain"))
    # Mirrors reconcile_installation's real signature, default included. A stub
    # that swallowed **kwargs would record a handler that passes no trigger
    # identically to one that asks for the sweep's terms, and the difference
    # between those two is max_attempts paid model reads per redelivery.
    monkeypatch.setattr(
        worker,
        "reconcile_installation",
        lambda i, *, trigger="live": kicks.append((i, trigger)),
    )
    return kicks


def _webhook(event: str, payload: dict, secret: str = SECRET):
    body = json.dumps(payload).encode()
    return client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": event,
            "X-Hub-Signature-256": _sig(secret.encode(), body, "sha256"),
        },
    )


def _table(tmp_path, table) -> list[dict]:
    with create_engine(f"sqlite:///{tmp_path}/doug.db").connect() as conn:
        return [dict(r) for r in conn.execute(select(table)).mappings()]


def _utc(dt: datetime) -> datetime:
    """sqlite hands a DateTime(timezone=True) column back naive; Postgres
    hands it back aware. The stored instant is UTC either way, so normalise
    before comparing — otherwise these assertions would be about the driver
    rather than about the timestamp."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def test_installation_created_records_the_account_and_its_repos(tmp_path, monkeypatch):
    """The authoritative repo list arrives exactly once, on this event.
    Everything after it is a delta, so getting this write wrong means an
    installation whose repo set is never correct again."""
    kicks = _hook_env(tmp_path, monkeypatch)
    r = _webhook(
        "installation",
        {
            "action": "created",
            "installation": INSTALLATION,
            "repositories": [
                {"id": 987, "full_name": "drewjst/doug"},
                {"id": 988, "full_name": "drewjst/other"},
            ],
        },
    )
    assert r.status_code == 202

    (inst,) = _table(tmp_path, store.installations)
    assert inst["installation_id"] == 150424894
    assert inst["account_login"] == "drewjst" and inst["account_type"] == "User"
    assert inst["state"] == "active"

    repos = {r["github_repo_id"]: r for r in _table(tmp_path, store.installation_repos)}
    assert set(repos) == {987, 988}
    assert repos[987]["full_name"] == "drewjst/doug"
    assert all(r["state"] == "active" for r in repos.values())
    # Reconcile is queued, not run inline: it lists open PRs over the
    # network and the 202 must not wait on it. The drain is chained behind
    # it inside the same task — see the dedicated test below, and the one
    # after it for the terms this call passes.
    assert kicks == [(150424894, "reconcile"), "drain"]


def test_installation_created_records_the_installer(tmp_path, monkeypatch):
    """Task 5's bind endpoint proves "you are the person who installed Doug
    here" by matching this column against the signed-in GitHub user — it has
    to come from the one action that actually names an installer."""
    _hook_env(tmp_path, monkeypatch)
    _webhook(
        "installation",
        {
            "action": "created",
            "installation": INSTALLATION,
            "repositories": [],
            "sender": {"id": 42, "login": "drewjst"},
        },
    )
    assert _table(tmp_path, store.installations)[0]["installed_by_github_user_id"] == 42


def test_installation_created_tolerates_a_missing_sender(tmp_path, monkeypatch):
    """Older redeliveries and synthetic payloads can omit or malform sender.
    The installation row is more important than who's on it, so this must
    record the installation rather than raise."""
    _hook_env(tmp_path, monkeypatch)
    r = _webhook(
        "installation",
        {"action": "created", "installation": INSTALLATION, "repositories": []},
    )
    assert r.status_code == 202
    assert _table(tmp_path, store.installations)[0]["installed_by_github_user_id"] is None


def test_suspend_does_not_overwrite_the_recorded_installer(tmp_path, monkeypatch):
    """suspend/unsuspend/deleted deliveries name whoever performed THAT
    action, not who installed Doug — passing their sender through would
    misattribute Task 5's bind proof to the wrong person."""
    _hook_env(tmp_path, monkeypatch)
    _webhook(
        "installation",
        {
            "action": "created",
            "installation": INSTALLATION,
            "repositories": [],
            "sender": {"id": 42, "login": "drewjst"},
        },
    )
    _webhook(
        "installation",
        {
            "action": "suspend",
            "installation": INSTALLATION,
            "sender": {"id": 99, "login": "someone-else"},
        },
    )
    assert _table(tmp_path, store.installations)[0]["installed_by_github_user_id"] == 42


def test_uninstall_then_reinstall_converges_on_the_smaller_repo_set(tmp_path, monkeypatch):
    """Reinstalling on fewer repos must leave the dropped one uncovered, and
    the uninstall is what makes that true.

    installation_repos is the only record of what an installation covers,
    and active_repos is the only input the healing path has. A repo left
    'active' after it stopped being granted is not a bill — an installation
    token 403s on a repo it does not cover and reconcile swallows that with
    a log line — it is a permanently wrong coverage record that makes every
    pass log a skipped repo indistinguishable from a real outage on one
    Doug is actually installed on.

    An earlier version of this test ran two `created` deliveries back to
    back and read convergence out of `created` being a replacing write.
    Those two shapes are indistinguishable in the payload, and reading them
    that way is what made a redelivery drop a repo — see the test below."""
    _hook_env(tmp_path, monkeypatch)
    _webhook(
        "installation",
        {
            "action": "created",
            "installation": INSTALLATION,
            "repositories": [
                {"id": 987, "full_name": "drewjst/doug"},
                {"id": 988, "full_name": "drewjst/other"},
            ],
        },
    )
    _webhook("installation", {"action": "deleted", "installation": INSTALLATION})
    _webhook(
        "installation",
        {
            "action": "created",
            "installation": INSTALLATION,
            "repositories": [{"id": 987, "full_name": "drewjst/doug"}],
        },
    )
    repos = {r["github_repo_id"]: r for r in _table(tmp_path, store.installation_repos)}
    assert repos[987]["state"] == "active"
    # Still present — a removal never deletes — but no longer covered.
    assert repos[988]["state"] == "removed"


def test_a_redelivered_created_does_not_drop_a_repo_granted_since(tmp_path, monkeypatch):
    """`created` is authoritative when GitHub generates it, not when this
    service processes it.

    The Redeliver button in the App's Advanced tab is an ordinary cutover
    move, GitHub retries failed deliveries on its own schedule, and
    deliveries can simply arrive out of order. Any of those replays a
    `created` whose repo list predates every installation_repositories delta
    since. Treated as a replacing write it marks those repos 'removed', and
    because active_repos is what reconcile reads, that repo's backlog is
    then never healed again — silently, with no event that ever restores
    it. Live pull_request deliveries keep enqueuing, so nothing surfaces the
    gap."""
    _hook_env(tmp_path, monkeypatch)
    created = {
        "action": "created",
        "installation": INSTALLATION,
        "repositories": [{"id": 987, "full_name": "drewjst/doug"}],
    }
    _webhook("installation", created)
    _webhook(
        "installation_repositories",
        {
            "action": "added",
            "installation": INSTALLATION,
            "repositories_added": [{"id": 988, "full_name": "drewjst/other"}],
        },
    )
    # The original delivery, replayed.
    _webhook("installation", created)
    repos = {r["github_repo_id"]: r for r in _table(tmp_path, store.installation_repos)}
    assert repos[987]["state"] == "active"
    assert repos[988]["state"] == "active"
    assert sorted(store.active_repos(150424894)) == [
        (987, "drewjst/doug"),
        (988, "drewjst/other"),
    ]


def test_installation_deleted_flips_state_without_dropping_history(tmp_path, monkeypatch):
    """Uninstalling ends the permission, not the record. Deleting rows
    would take the tenancy context off every verdict already written, and
    reinstalling is the single most common thing a trialling team does.

    The repo rows move with it: coverage ended, so active_repos must stop
    returning them, and the row survives because a verdict written while
    the repo was installed still has to resolve to the repo it describes."""
    _hook_env(tmp_path, monkeypatch)
    _webhook(
        "installation",
        {
            "action": "created",
            "installation": INSTALLATION,
            "repositories": [{"id": 987, "full_name": "drewjst/doug"}],
        },
    )
    assert (
        _webhook(
            "installation", {"action": "deleted", "installation": INSTALLATION}
        ).status_code
        == 202
    )

    (inst,) = _table(tmp_path, store.installations)
    assert inst["state"] == "deleted"
    (repo,) = _table(tmp_path, store.installation_repos)
    assert repo["github_repo_id"] == 987 and repo["state"] == "removed"
    assert store.active_repos(150424894) == []


def test_installation_suspend_and_unsuspend_round_trip(tmp_path, monkeypatch):
    _hook_env(tmp_path, monkeypatch)
    _webhook(
        "installation",
        {"action": "created", "installation": INSTALLATION, "repositories": []},
    )
    _webhook("installation", {"action": "suspend", "installation": INSTALLATION})
    assert _table(tmp_path, store.installations)[0]["state"] == "suspended"
    _webhook("installation", {"action": "unsuspend", "installation": INSTALLATION})
    assert _table(tmp_path, store.installations)[0]["state"] == "active"


def test_installation_repositories_merges_both_deltas(tmp_path, monkeypatch):
    """One delivery can carry both lists. A removal marks state rather than
    deleting the row, so a verdict written while the repo was installed
    still resolves to the repo it was written about."""
    _hook_env(tmp_path, monkeypatch)
    _webhook(
        "installation",
        {
            "action": "created",
            "installation": INSTALLATION,
            "repositories": [{"id": 987, "full_name": "drewjst/doug"}],
        },
    )
    r = _webhook(
        "installation_repositories",
        {
            "action": "added",
            "installation": INSTALLATION,
            "repositories_added": [{"id": 988, "full_name": "drewjst/other"}],
            "repositories_removed": [{"id": 987, "full_name": "drewjst/doug"}],
        },
    )
    assert r.status_code == 202
    repos = {r["github_repo_id"]: r for r in _table(tmp_path, store.installation_repos)}
    assert repos[987]["state"] == "removed"
    assert repos[988]["state"] == "active"


def test_a_new_installation_reviews_its_backlog_without_waiting(tmp_path, monkeypatch):
    """reconcile_installation only enqueues. Chaining the drain behind it is
    what makes the cutover's "a check run appears within seconds of
    installing" true — otherwise a fresh install's whole backlog sits
    pending until somebody happens to open the next PR, which on a quiet
    repo can be days. Order matters: draining first would drain an empty
    queue."""
    kicks = _hook_env(tmp_path, monkeypatch)
    _webhook(
        "installation",
        {"action": "created", "installation": INSTALLATION, "repositories": []},
    )
    assert kicks == [(150424894, "reconcile"), "drain"]


def test_the_installation_created_handler_asks_for_the_sweeps_terms(tmp_path, monkeypatch):
    """The handler must name its own terms, not inherit reconcile_installation's.

    installation.created lists every open PR of an installation whether or not
    anything about them changed, which is the sweep half of the distinction
    reconcile_installation's `trigger` draws — and it is replayable (the App's
    Advanced tab Redeliver button, or GitHub retrying a delivery), which
    _record_installation's own comment already treats as ordinary. Left to the
    live default, each replay revives every 'failed' row at once and re-arms
    max_attempts paid model reads for a PR that has already burned them, which
    is the spend leak FAILED_REVIVE_COOLOFF_SECONDS exists to close.

    Asserted at the call site rather than on the function, because dropping the
    argument is exactly how the leak comes back: the function's own contract
    (test_reconcile_installation_takes_live_terms_unless_the_sweep_asks_otherwise)
    stays satisfied while the handler silently changes what it buys.
    """
    kicks = _hook_env(tmp_path, monkeypatch)
    _webhook(
        "installation",
        {"action": "created", "installation": INSTALLATION, "repositories": []},
    )
    assert kicks == [(150424894, "reconcile"), "drain"]


def test_a_redelivered_installation_created_does_not_re_arm_a_failed_pr(
    tmp_path, monkeypatch, capsys
):
    """The same thing again, through the real reconcile rather than a stub.

    The stub above pins the argument; this pins what the argument buys, and it
    is the assertion that survives someone rewriting the seam. A PR that burned
    all three attempts on the first delivery must still be 'failed' after a
    redelivery inside the cooloff — and the operator who redelivered must be
    told that in the log, because "held back for another 3000s" and "already
    reviewed" are otherwise the same silence.
    """
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/doug.db")
    assert store.enabled()
    job_id = ingest.enqueue(
        150424894, 987, "drewjst/doug", 7, "a" * 40, base_sha="0" * 40
    )
    for _ in range(3):
        claimed = ingest.claim()
        assert claimed["id"] == job_id
        assert ingest.fail(
            job_id, "credentials missing", claim_generation=claimed["claim_generation"]
        )

    pull = SimpleNamespace(
        number=7,
        draft=False,
        head=SimpleNamespace(sha="a" * 40, repo=SimpleNamespace(id=987)),
        base=SimpleNamespace(
            sha="0" * 40,
            repo=SimpleNamespace(id=987, full_name="drewjst/doug"),
        ),
    )
    monkeypatch.setattr(
        worker.app_auth,
        "installation_client",
        lambda i: SimpleNamespace(
            rest=SimpleNamespace(
                pulls=SimpleNamespace(list=lambda **kw: SimpleNamespace(parsed_data=[pull]))
            )
        ),
    )
    # Only the drain is cut: it would otherwise run the real pipeline against
    # whatever this test revived, which is the thing being asserted about.
    monkeypatch.setattr(worker, "drain", lambda *a, **k: None)

    _webhook(
        "installation",
        {
            "action": "created",
            "installation": INSTALLATION,
            "repositories": [{"id": 987, "full_name": "drewjst/doug"}],
        },
    )

    (job,) = _table(tmp_path, store.review_jobs)
    assert job["id"] == job_id
    assert job["status"] == "failed" and job["attempts"] == 3, "the redelivery re-armed it"
    err = capsys.readouterr().err
    assert "drewjst/doug#7" in err and "cooloff" in err


def test_only_a_new_installation_kicks_reconcile(tmp_path, monkeypatch):
    """Suspend/unsuspend/delete change state and nothing else. Reconciling on
    them would list every open PR of an installation that just told us to
    stop looking at it."""
    kicks = _hook_env(tmp_path, monkeypatch)
    for action in ("suspend", "unsuspend", "deleted"):
        _webhook("installation", {"action": action, "installation": INSTALLATION})
    assert kicks == []


def _pr_payload(
    action="opened",
    *,
    draft=False,
    head_repo_id=987,
    sha="a" * 40,
    base_sha="0" * 40,
    number=7,
):
    head_repo = None if head_repo_id is None else {"id": head_repo_id}
    return {
        "action": action,
        "installation": INSTALLATION,
        "pull_request": {
            "number": number,
            "draft": draft,
            "head": {"sha": sha, "repo": head_repo},
            "base": {
                "sha": base_sha,
                "repo": {"id": 987, "full_name": "drewjst/doug"},
            },
        },
    }


def test_a_pull_request_event_enqueues_one_durable_job(tmp_path, monkeypatch):
    """The 202 has to mean the work survives this instance. GitHub
    redelivers on its own terms and reconcile is the backstop — neither is
    a reason to answer 202 for a job held only in memory."""
    kicks = _hook_env(tmp_path, monkeypatch)
    assert _webhook("pull_request", _pr_payload()).status_code == 202

    (j,) = _table(tmp_path, store.review_jobs)
    assert j["installation_id"] == 150424894
    assert j["github_repo_id"] == 987
    assert j["repo_full_name"] == "drewjst/doug"
    assert j["pr_number"] == 7 and j["head_sha"] == "a" * 40
    assert j["base_sha"] == "0" * 40
    assert j["status"] == "pending"
    assert kicks == ["drain"]


def test_missing_base_sha_is_logged_and_not_enqueued(tmp_path, monkeypatch, capsys):
    """A 202 may acknowledge a malformed GitHub delivery, but it must not
    mint a job whose comparison identity is already incomplete."""
    kicks = _hook_env(tmp_path, monkeypatch)

    response = _webhook("pull_request", _pr_payload(base_sha=None))

    assert response.status_code == 202
    assert _table(tmp_path, store.review_jobs) == []
    assert kicks == []
    assert "base.sha" in capsys.readouterr().err


def test_every_head_moving_action_enqueues(tmp_path, monkeypatch):
    _hook_env(tmp_path, monkeypatch)
    for i, action in enumerate(("opened", "synchronize", "reopened", "ready_for_review")):
        _webhook("pull_request", _pr_payload(action, sha=f"{i}" * 40))
    assert len(_table(tmp_path, store.review_jobs)) == 4


def test_a_draft_pull_request_is_not_enqueued(tmp_path, monkeypatch):
    """A read per push on a branch nobody has asked for review on is spend
    with no consumer. ready_for_review admits it later."""
    kicks = _hook_env(tmp_path, monkeypatch)
    assert _webhook("pull_request", _pr_payload(draft=True)).status_code == 202
    assert _table(tmp_path, store.review_jobs) == []
    assert kicks == []


def test_a_fork_pull_request_is_not_enqueued(tmp_path, monkeypatch):
    """The raw diff enters the prompt (reader._user_text). If forks
    enqueued, any GitHub user could drive this account's model spend by
    opening PRs against a public repo — no install, no relationship."""
    _hook_env(tmp_path, monkeypatch)
    assert _webhook("pull_request", _pr_payload(head_repo_id=555)).status_code == 202
    assert _table(tmp_path, store.review_jobs) == []


def test_a_pull_request_whose_fork_was_deleted_is_not_enqueued(tmp_path, monkeypatch):
    """head.repo is null once the fork is gone. It must fail the fork gate
    rather than raise — a KeyError here 500s and GitHub redelivers it."""
    _hook_env(tmp_path, monkeypatch)
    assert _webhook("pull_request", _pr_payload(head_repo_id=None)).status_code == 202
    assert _table(tmp_path, store.review_jobs) == []


def test_a_redelivery_of_the_same_head_sha_does_not_duplicate(tmp_path, monkeypatch):
    """GitHub redelivers on its own schedule, and 'opened' then
    'synchronize' for one push is normal. Two deliveries of one commit must
    be one review, not two paid reads."""
    _hook_env(tmp_path, monkeypatch)
    _webhook("pull_request", _pr_payload("opened"))
    _webhook("pull_request", _pr_payload("synchronize"))
    assert len(_table(tmp_path, store.review_jobs)) == 1


def test_a_new_head_sha_enqueues_a_second_job(tmp_path, monkeypatch):
    _hook_env(tmp_path, monkeypatch)
    _webhook("pull_request", _pr_payload("opened"))
    _webhook("pull_request", _pr_payload("synchronize", sha="b" * 40))
    shas = sorted(j["head_sha"] for j in _table(tmp_path, store.review_jobs))
    assert shas == ["a" * 40, "b" * 40]


# Deliberately nowhere near now(): every assertion about the observation
# window below is only worth something if a wall-clock implementation fails
# it, and one merged today would agree with now() to within a rounding error.
MERGED_AT = "2020-03-01T12:00:00Z"


def _closed_payload(
    *,
    merged=True,
    merged_at=MERGED_AT,
    merge_sha="c" * 40,
    number=7,
    base_ref="main",
    base_repo_id=987,
    head_sha="a" * 40,
):
    """A `closed` delivery. `merged` varies independently of the other two
    fields on purpose — see test_a_closed_but_unmerged_pull_request_writes_nothing.

    `head_sha=None` omits `pull_request.head` entirely rather than sending a
    null sha inside it — that is the shape GitHub itself sends when the head
    branch (usually a fork) is gone by the time the close event is built, and
    it is what test_missing_head_sha_does_not_suppress_the_clock exercises.
    """
    pr = {
        "number": number,
        "draft": False,
        "merged": merged,
        "merged_at": merged_at,
        "merge_commit_sha": merge_sha,
        "base": {"ref": base_ref, "repo": {"id": base_repo_id, "full_name": "drewjst/doug"}},
    }
    if head_sha is not None:
        pr["head"] = {"sha": head_sha, "repo": {"id": 987}}
    return {
        "action": "closed",
        "installation": INSTALLATION,
        "pull_request": pr,
    }


def test_a_merged_pull_request_starts_the_outcome_clock_without_buying_a_read(
    tmp_path, monkeypatch
):
    """The merge is the outcome loop's ignition — and it must never buy a
    model read. A closed PR has no new diff to review, so the only thing
    this delivery may do is record that the observation window has started.

    The ids come off the payload, never parsed out of a name: full_name is
    a display string that changes under a rename, and the denominator this
    row eventually feeds is published."""
    kicks = _hook_env(tmp_path, monkeypatch)
    assert _webhook("pull_request", _closed_payload()).status_code == 202

    jobs = sorted(_table(tmp_path, store.outcome_jobs), key=lambda row: row["window_days"])
    assert [job["window_days"] for job in jobs] == [14, 60]
    assert {job["installation_id"] for job in jobs} == {150424894}
    assert {job["github_repo_id"] for job in jobs} == {987}
    assert {job["pr_number"] for job in jobs} == {7}
    assert {job["merge_commit_sha"] for job in jobs} == {"c" * 40}
    assert {job["base_ref"] for job in jobs} == {"main"}
    assert [_utc(job["due_at"]) for job in jobs] == [
        datetime(2020, 3, 15, 12, 0, tzinfo=UTC),
        datetime(2020, 4, 30, 12, 0, tzinfo=UTC),
    ]
    assert all(job["status"] == "pending" for job in jobs)
    # No read bought, and nothing queued that would buy one.
    assert _table(tmp_path, store.review_jobs) == []
    assert kicks == []


def test_the_outcome_windows_are_measured_from_the_merge_not_from_now(tmp_path, monkeypatch):
    """due_at is merged_at + each window, computed from the payload's own
    timestamp. Deriving it from the wall clock would silently re-date every
    row a redelivery or a backfill ever touched, and the window is what the
    published defect-rate denominator means."""
    _hook_env(tmp_path, monkeypatch)
    _webhook("pull_request", _closed_payload())

    jobs = sorted(_table(tmp_path, store.outcome_jobs), key=lambda row: row["window_days"])
    assert [_utc(job["merged_at"]) for job in jobs] == [
        datetime(2020, 3, 1, 12, 0, tzinfo=UTC),
        datetime(2020, 3, 1, 12, 0, tzinfo=UTC),
    ]
    assert [_utc(job["due_at"]) for job in jobs] == [
        datetime(2020, 3, 15, 12, 0, tzinfo=UTC),
        datetime(2020, 4, 30, 12, 0, tzinfo=UTC),
    ]


def test_a_redelivered_merge_does_not_start_a_second_clock(tmp_path, monkeypatch):
    """GitHub redelivers on its own schedule. Two 'closed' deliveries for one
    merge must be one pair of observation windows, not a second pair — a
    second row would be a second vote in the denominator for a single merge."""
    _hook_env(tmp_path, monkeypatch)
    assert _webhook("pull_request", _closed_payload()).status_code == 202
    assert _webhook("pull_request", _closed_payload()).status_code == 202
    assert len(_table(tmp_path, store.outcome_jobs)) == 2


def test_a_redelivered_merge_heals_a_missing_outcome_window(tmp_path, monkeypatch):
    """A pre-M3 row can carry only the legacy 14-day identity. Redelivery
    must fill its missing 60-day partner rather than treating the whole merge
    as already queued, which proves the webhook uses the plural writer."""
    _hook_env(tmp_path, monkeypatch)
    assert store.enqueue_outcome_job(
        150424894,
        987,
        7,
        "c" * 40,
        datetime(2020, 3, 1, 12, 0, tzinfo=UTC),
        "main",
    ) is not None

    assert _webhook("pull_request", _closed_payload()).status_code == 202

    jobs = sorted(_table(tmp_path, store.outcome_jobs), key=lambda row: row["window_days"])
    assert [job["window_days"] for job in jobs] == [14, 60]


def test_merge_records_the_head_sha_that_merged(tmp_path, monkeypatch):
    """Pre-registration §11 item 7: a receipt claims a verdict about the
    code that actually merged, and that claim needs the merge commit's own
    head sha recorded going forward, not just the merge timestamp."""
    _hook_env(tmp_path, monkeypatch)
    assert _webhook("pull_request", _closed_payload(head_sha="abc123")).status_code == 202

    jobs = _table(tmp_path, store.outcome_jobs)
    assert jobs, "the clock must start"
    assert {job["merged_head_sha"] for job in jobs} == {"abc123"}


def test_missing_head_sha_does_not_suppress_the_clock(tmp_path, monkeypatch):
    """merged_head_sha is evidence, not one of the five load-bearing facts
    test_a_merge_missing_the_facts_the_row_is_built_from_is_ignored guards.
    _record_merge drops the whole row when base_ref or github_repo_id is
    missing, because those drive censoring and tenancy. This one drives
    neither, so its absence must cost nothing — both windows still start."""
    _hook_env(tmp_path, monkeypatch)
    assert _webhook("pull_request", _closed_payload(head_sha=None)).status_code == 202

    jobs = _table(tmp_path, store.outcome_jobs)
    assert len(jobs) == 2, "both windows still start"
    assert all(job["merged_head_sha"] is None for job in jobs)


def test_a_closed_but_unmerged_pull_request_writes_nothing(tmp_path, monkeypatch):
    """An abandoned PR has no merge to observe the consequences of. Recording
    one would put a PR that never shipped into the denominator of a claim
    about shipped code.

    `merged` is the only field that decides this, which is why the payload
    below still carries a merge_commit_sha and a merged_at. Those two are
    not evidence a merge happened — merge_commit_sha in particular is a
    field GitHub also populates with a computed test-merge commit — so a
    guard that keyed off their presence instead of off the flag would
    enqueue an observation window for a PR that never landed. The first
    version of this test nulled them alongside the flag and therefore passed
    against a build with no `merged` check at all."""
    _hook_env(tmp_path, monkeypatch)
    assert _webhook("pull_request", _closed_payload(merged=False)).status_code == 202
    assert _table(tmp_path, store.outcome_jobs) == []
    assert _table(tmp_path, store.review_jobs) == []


def test_a_merge_missing_the_facts_the_row_is_built_from_is_ignored(tmp_path, monkeypatch):
    """when it shipped, what shipped, where, which PR, whose repo — the five
    facts an outcome row IS. A half-row is worse than no row here: base_ref
    is what the adjudicator censors on, and github_repo_id is the tenancy it
    is counted under, so a row built from a default would put a PR into a
    published denominator under a repo nobody chose.

    Every _closed_payload() call before this one used the defaults, so this
    guard shipped completely unexercised — a 36-mutation battery replaced it
    with `if False:` and all 402 tests stayed green."""
    _hook_env(tmp_path, monkeypatch)
    for payload in (
        _closed_payload(merged_at=None),
        _closed_payload(merged_at="not-a-timestamp"),
        _closed_payload(merge_sha=None),
        _closed_payload(merge_sha=""),
        # Not a string at all: "absent" and "unusable" have to reach the
        # same guard, or the value goes to a VARCHAR column as an int.
        _closed_payload(merge_sha=123),
        _closed_payload(base_ref=None),
        _closed_payload(base_ref=""),
        _closed_payload(base_ref=["main"]),
        _closed_payload(number=None),
        _closed_payload(number="7"),
        _closed_payload(base_repo_id=None),
        _closed_payload(base_repo_id="987"),
    ):
        assert _webhook("pull_request", payload).status_code == 202
    assert _table(tmp_path, store.outcome_jobs) == []


def test_facts_too_long_for_their_columns_are_refused_rather_than_written(
    tmp_path, monkeypatch
):
    """Postgres answers an over-long INSERT with StringDataRightTruncation —
    a 500, and so the same redelivery loop the shape guards prevent. sqlite
    stores the long value instead, so this test asserts the guard (no row)
    rather than the driver's error: it would pass on sqlite either way if the
    guard were gone, which is exactly why the guard cannot be left to the
    database.

    Refused rather than truncated: a cut SHA names a different commit and a
    cut full_name names a different repo."""
    _hook_env(tmp_path, monkeypatch)
    long_name = "drewjst/" + "d" * 200
    long_sha = "a" * 200

    pr = _pr_payload(sha=long_sha)
    assert _webhook("pull_request", pr).status_code == 202
    pr = _pr_payload()
    pr["pull_request"]["base"]["repo"]["full_name"] = long_name
    assert _webhook("pull_request", pr).status_code == 202
    assert _table(tmp_path, store.review_jobs) == []

    assert _webhook("pull_request", _closed_payload(merge_sha=long_sha)).status_code == 202
    assert _webhook("pull_request", _closed_payload(base_ref="b" * 300)).status_code == 202
    assert _table(tmp_path, store.outcome_jobs) == []

    assert _webhook("pull_request_review", _review_payload(login="l" * 80)).status_code == 202
    assert _webhook("pull_request_review", _review_payload(commit_id=long_sha)).status_code == 202
    review = _review_payload()
    review["pull_request"]["base"]["repo"]["full_name"] = long_name
    assert _webhook("pull_request_review", review).status_code == 202
    assert _table(tmp_path, store.verdicts) == []

    inst = {
        "action": "created",
        "installation": INSTALLATION,
        "repositories": [{"id": 987, "full_name": long_name}],
    }
    assert _webhook("installation", inst).status_code == 202
    assert _table(tmp_path, store.installation_repos) == []


SUBMITTED_AT = "2026-07-20T09:30:00Z"


def _review_payload(
    state="approved",
    *,
    action="submitted",
    login="alice",
    commit_id="a" * 40,
    submitted_at=SUBMITTED_AT,
    review_id=55,
    number=7,
    head_repo_id=987,
    base_repo_id=987,
):
    return {
        "action": action,
        "installation": INSTALLATION,
        "review": {
            "id": review_id,
            "state": state,
            "submitted_at": submitted_at,
            "commit_id": commit_id,
            "user": {"login": login},
        },
        "pull_request": {
            "number": number,
            "head": {"repo": {"id": head_repo_id}},
            "base": {"repo": {"id": base_repo_id, "full_name": "drewjst/doug"}},
        },
    }


def test_an_approving_review_is_ingested_as_a_dated_external_stance(
    tmp_path, monkeypatch
):
    """The neutral-grader lane. A third-party stance lands in the same ledger
    as Doug's verdicts, in Doug's own band vocabulary, so the two can be
    adjudicated against the same outcome — and nothing is spent doing it: no
    model call, no metering, no check run.

    scored_at is the reviewer's submitted_at, not now(). The row is a dated
    claim about when the stance was taken."""
    kicks = _hook_env(tmp_path, monkeypatch)
    assert _webhook("pull_request_review", _review_payload()).status_code == 202

    (v,) = _table(tmp_path, store.verdicts)
    assert v["tier"] == "external"
    assert v["score"] == 0.0 and v["threshold"] == 0.0
    assert v["band"] == "cleared"
    assert v["source"] == "review:alice"
    assert v["installation_id"] == 150424894 and v["github_repo_id"] == 987
    assert v["repo"] == "drewjst/doug" and v["pr_number"] == 7
    assert v["head_sha"] == "a" * 40
    assert _utc(v["scored_at"]) == datetime(2026, 7, 20, 9, 30, tzinfo=UTC)
    assert v["raw"]["review_id"] == 55 and v["raw"]["state"] == "approved"
    # Nothing was read, so nothing may claim to have been.
    assert _table(tmp_path, store.findings) == []
    assert _table(tmp_path, store.reads) == []
    # And nothing was queued that would buy a read.
    assert _table(tmp_path, store.review_jobs) == []
    assert kicks == []


def test_a_changes_requested_review_lands_as_flagged(tmp_path, monkeypatch):
    """The two stances map onto Doug's own bands. Recording both as the same
    thing would make the lane useless for grading a reviewer against
    outcomes, which is its entire purpose."""
    _hook_env(tmp_path, monkeypatch)
    _webhook("pull_request_review", _review_payload("changes_requested"))
    (v,) = _table(tmp_path, store.verdicts)
    assert v["band"] == "flagged"


def test_a_review_that_takes_no_stance_is_not_recorded(tmp_path, monkeypatch):
    """`commented` is a note, not a position on whether the change should
    land. There is nothing to grade against an outcome, so there is no row."""
    _hook_env(tmp_path, monkeypatch)
    for state in ("commented", "pending", "dismissed"):
        assert (
            _webhook("pull_request_review", _review_payload(state)).status_code == 202
        )
    assert _table(tmp_path, store.verdicts) == []


def test_a_rest_cased_review_state_bands_the_same_as_a_webhook_cased_one(
    tmp_path, monkeypatch
):
    """GitHub spells one state two ways: this webhook delivers `approved`,
    and the REST reviews endpoint returns `APPROVED` for that same review —
    which is the spelling review._review_state matches. Nothing in the
    payload says which vocabulary it came from, so the band must not depend
    on the casing.

    Being wrong about that fails silently, in the direction that looks like a
    quiet week: an unmatched state takes the no-band return, so every review
    would drop, the tier-`external` lane would ingest nothing, and GitHub
    would still get its 202. That lane is the denominator the outcome loop
    publishes against, so the damage is a claim computed over nothing."""
    _hook_env(tmp_path, monkeypatch)
    assert _webhook("pull_request_review", _review_payload("APPROVED")).status_code == 202
    _webhook(
        "pull_request_review",
        _review_payload(
            "CHANGES_REQUESTED", submitted_at="2026-07-20T11:00:00Z", review_id=56
        ),
    )
    rows = _table(tmp_path, store.verdicts)
    assert [v["band"] for v in rows] == ["cleared", "flagged"]
    assert [v["tier"] for v in rows] == ["external", "external"]
    assert [v["source"] for v in rows] == ["review:alice", "review:alice"]
    # Normalising decides the band; it does not rewrite the ledger. raw is
    # what GitHub actually sent, which is the only copy of that fact.
    assert [v["raw"]["state"] for v in rows] == ["APPROVED", "CHANGES_REQUESTED"]


def test_an_unrecognized_review_state_is_logged_rather_than_dropped_in_silence(
    tmp_path, monkeypatch, capsys
):
    """A state in neither set is the hazard normalising does not close:
    GitHub adds a review state, or one was never accounted for. No row is
    written — a stance we cannot read is not a gradable claim — but this is
    the one drop on this path that nobody chose, so it must not be silent.
    Silent, an ingest-nothing lane is indistinguishable from a quiet week,
    and there is no error and no 4xx anywhere else to notice it by."""
    _hook_env(tmp_path, monkeypatch)
    assert _webhook("pull_request_review", _review_payload("endorsed")).status_code == 202
    assert _table(tmp_path, store.verdicts) == []
    assert "carried unrecognized state 'endorsed'" in capsys.readouterr().err


def test_a_review_state_we_deliberately_do_not_band_is_skipped_without_a_log_line(
    tmp_path, monkeypatch, capsys
):
    """`commented` is by far the most common review state on GitHub and
    `dismissed` is routine. Both are skipped on purpose, so neither may log:
    a warning that fires on the normal case is one an operator learns to
    scroll past, which costs exactly the signal the unrecognized-state line
    exists to carry. That makes the silence load-bearing, not incidental.

    Both spellings, for the reason the casing test above gives."""
    _hook_env(tmp_path, monkeypatch)
    for state in ("commented", "COMMENTED", "dismissed", "pending"):
        assert _webhook("pull_request_review", _review_payload(state)).status_code == 202
    assert _table(tmp_path, store.verdicts) == []
    assert capsys.readouterr().err == ""


def test_only_a_submitted_review_is_recorded(tmp_path, monkeypatch):
    """`edited` and `dismissed` restate or retract a review that was already
    ingested when it was submitted. Treating them as new stances would count
    one reviewer's position two or three times."""
    _hook_env(tmp_path, monkeypatch)
    for action in ("edited", "dismissed"):
        r = _webhook("pull_request_review", _review_payload(action=action))
        assert r.status_code == 202
    assert _table(tmp_path, store.verdicts) == []


def test_a_redelivered_review_is_ingested_once(tmp_path, monkeypatch):
    """Same reviewer, same head, same timestamp — one stance, however many
    times GitHub sends it. Two rows would double that reviewer's weight in
    any agreement measure taken over this ledger."""
    _hook_env(tmp_path, monkeypatch)
    _webhook("pull_request_review", _review_payload())
    _webhook("pull_request_review", _review_payload())
    assert len(_table(tmp_path, store.verdicts)) == 1


def test_a_reviewer_changing_their_mind_records_both_stances(tmp_path, monkeypatch):
    """approve then changes_requested on the same commit is two real
    positions at two times, not a correction. The ledger is append-only
    dated claims, and the sequence is exactly what makes a reviewer worth
    grading."""
    _hook_env(tmp_path, monkeypatch)
    _webhook("pull_request_review", _review_payload("approved"))
    _webhook(
        "pull_request_review",
        _review_payload(
            "changes_requested", submitted_at="2026-07-20T11:00:00Z", review_id=56
        ),
    )
    bands = [v["band"] for v in _table(tmp_path, store.verdicts)]
    assert bands == ["cleared", "flagged"]


def test_a_bot_reviewer_is_ingested_like_anyone_else(tmp_path, monkeypatch):
    """Grading bot reviewers against outcomes is the point of this lane, so
    there is deliberately no bot filter here — unlike the review-enqueue
    path, where a stranger's PR can drive spend. Nothing is spent ingesting
    a stance."""
    _hook_env(tmp_path, monkeypatch)
    _webhook("pull_request_review", _review_payload(login="some-reviewer[bot]"))
    (v,) = _table(tmp_path, store.verdicts)
    assert v["source"] == "review:some-reviewer[bot]"


def test_a_review_on_a_fork_pull_request_is_still_ingested(tmp_path, monkeypatch):
    """The fork gate exists because a fork's raw diff enters the prompt and
    an outsider could drive model spend. Ingesting a stance reads nothing
    and spends nothing, so that gate does not apply — and a review left on
    an outside contributor's PR is exactly as gradable as any other."""
    _hook_env(tmp_path, monkeypatch)
    _webhook("pull_request_review", _review_payload(head_repo_id=555))
    assert len(_table(tmp_path, store.verdicts)) == 1
    assert _table(tmp_path, store.review_jobs) == []


def test_a_review_missing_the_facts_it_would_be_dated_by_is_ignored(
    tmp_path, monkeypatch
):
    """head_sha and scored_at are the row's identity and its dedup key. A
    stance that cannot be attached to a commit or to a time is not a
    gradable claim, so it is dropped rather than stored against a guess."""
    _hook_env(tmp_path, monkeypatch)
    for payload in (
        _review_payload(commit_id=None),
        _review_payload(submitted_at=None),
        _review_payload(submitted_at="not-a-timestamp"),
        _review_payload(login=None),
        _review_payload(base_repo_id=None),
        # Present but not a string: same guard, or an int reaches a VARCHAR.
        _review_payload(commit_id=99),
        _review_payload(login={"name": "alice"}),
        _review_payload(base_repo_id="987"),
        _review_payload(number=None),
    ):
        assert _webhook("pull_request_review", payload).status_code == 202
    assert _table(tmp_path, store.verdicts) == []


def test_unhandled_pull_request_actions_are_accepted_and_ignored(tmp_path, monkeypatch):
    """labeled/edited/review_requested/converted_to_draft do not change the
    diff. A 4xx would put GitHub into a redelivery loop over events we chose
    not to handle, so they are 202 — but they must not reach the queue.

    'closed' is deliberately absent: it IS handled, on its own branch that
    starts the outcome clock without buying a read."""
    kicks = _hook_env(tmp_path, monkeypatch)
    for action in ("labeled", "edited", "review_requested", "converted_to_draft"):
        assert _webhook("pull_request", _pr_payload(action)).status_code == 202
    assert _table(tmp_path, store.review_jobs) == []
    assert kicks == []


def test_unhandled_events_are_accepted_and_ignored(tmp_path, monkeypatch):
    _hook_env(tmp_path, monkeypatch)
    for event in ("push", "check_suite", "issues", "installation_target"):
        r = _webhook(event, {"action": "created", "installation": INSTALLATION})
        assert r.status_code == 202
    assert _table(tmp_path, store.review_jobs) == []
    assert _table(tmp_path, store.installations) == []


def test_ping_is_accepted_without_an_installation(tmp_path, monkeypatch):
    """The App's first delivery, and the only one production has ever sent
    (2026-07-31 23:23:32) — it went through the discard path, so no handler
    that parses a body has ever seen it. Pinging from the App settings page
    rather than from an installation sends no installation key at all, so
    nothing downstream of here may reach for one."""
    _hook_env(tmp_path, monkeypatch)
    assert (
        _webhook("ping", {"zen": "Non-blocking is better than blocking."}).status_code
        == 202
    )


def test_a_payload_with_no_usable_installation_is_ignored(tmp_path, monkeypatch):
    """Every branch past the guard indexes installation["id"], so the guard
    checks the id and not just the key. Otherwise a malformed-but-signed
    payload is a KeyError 500, and GitHub redelivers it into the same 500.

    All three shapes are quiet 202s: absent, explicitly null, and present
    but id-less."""
    _hook_env(tmp_path, monkeypatch)
    for payload in (
        {"action": "opened"},
        {"action": "opened", "installation": None},
        {"action": "opened", "installation": {"account": {"login": "drewjst"}}},
    ):
        assert _webhook("pull_request", payload).status_code == 202
    assert _table(tmp_path, store.review_jobs) == []
    assert _table(tmp_path, store.installations) == []


# Signed deliveries that get PAST the installation guard and reach a handler
# with a shape it cannot use. The guard's own test above covers the shapes
# that exit AT the guard; these are the ones that get past it, which is
# where each handler has to be total over its own payload. Every one of
# these raised on this branch — a 500, which is exactly what GitHub
# redelivers, so each was a permanent loop over a body that will never carry
# what it is missing.
MALFORMED_DELIVERIES = [
    ("pr-no-pull_request", "pull_request", {"action": "opened"}),
    ("pr-empty-pull_request", "pull_request", {"action": "opened", "pull_request": {}}),
    (
        "pr-base-without-repo",
        "pull_request",
        {
            "action": "opened",
            "pull_request": {
                "number": 1,
                "draft": False,
                "base": {},
                "head": {"sha": "a" * 40, "repo": {"id": 987}},
            },
        },
    ),
    (
        "pr-no-head",
        "pull_request",
        {
            "action": "opened",
            "pull_request": {
                "number": 1,
                "draft": False,
                "base": {"repo": {"id": 987, "full_name": "drewjst/doug"}},
            },
        },
    ),
    (
        "pr-head-without-sha",
        "pull_request",
        {
            "action": "opened",
            "pull_request": {
                "number": 1,
                "draft": False,
                "base": {"repo": {"id": 987, "full_name": "drewjst/doug"}},
                "head": {"repo": {"id": 987}},
            },
        },
    ),
    (
        "pr-no-number",
        "pull_request",
        {
            "action": "opened",
            "pull_request": {
                "draft": False,
                "base": {"repo": {"id": 987, "full_name": "drewjst/doug"}},
                "head": {"sha": "a" * 40, "repo": {"id": 987}},
            },
        },
    ),
    (
        "pr-facts-that-are-not-strings",
        "pull_request",
        {
            "action": "opened",
            "pull_request": {
                "number": 1,
                "draft": False,
                "base": {"repo": {"id": 987, "full_name": 987}},
                "head": {"sha": 42, "repo": {"id": 987}},
            },
        },
    ),
    ("closed-no-pull_request", "pull_request", {"action": "closed"}),
    (
        "closed-merged-base-without-repo",
        "pull_request",
        {
            "action": "closed",
            "pull_request": {
                "number": 1,
                "merged": True,
                "merged_at": MERGED_AT,
                "merge_commit_sha": "c" * 40,
                "base": {"ref": "main"},
            },
        },
    ),
    (
        "closed-merged-no-number",
        "pull_request",
        {
            "action": "closed",
            "pull_request": {
                "merged": True,
                "merged_at": MERGED_AT,
                "merge_commit_sha": "c" * 40,
                "base": {"ref": "main", "repo": {"id": 987}},
            },
        },
    ),
    (
        "review-no-pr-number",
        "pull_request_review",
        {
            "action": "submitted",
            "pull_request": {"base": {"repo": {"id": 987, "full_name": "drewjst/doug"}}},
            "review": {
                "id": 5,
                "state": "approved",
                "commit_id": "a" * 40,
                "submitted_at": SUBMITTED_AT,
                "user": {"login": "bob"},
            },
        },
    ),
    ("review-is-a-list", "pull_request_review", {"action": "submitted", "review": []}),
    (
        "review-no-pull_request",
        "pull_request_review",
        {
            "action": "submitted",
            "review": {
                "id": 5,
                "state": "approved",
                "commit_id": "a" * 40,
                "submitted_at": SUBMITTED_AT,
                "user": {"login": "bob"},
            },
        },
    ),
    ("created-repositories-null", "installation", {"action": "created", "repositories": None}),
    (
        "created-repo-entry-without-full_name",
        "installation",
        {"action": "created", "repositories": [{"id": 987}]},
    ),
    (
        "created-repo-entry-without-id",
        "installation",
        {"action": "created", "repositories": [{"full_name": "drewjst/doug"}]},
    ),
    (
        "created-repositories-is-an-object",
        "installation",
        {"action": "created", "repositories": {"id": 987}},
    ),
    (
        "created-repo-entry-is-a-string",
        "installation",
        {"action": "created", "repositories": ["drewjst/doug"]},
    ),
    (
        "installation_repositories-added-null",
        "installation_repositories",
        {"action": "added", "repositories_added": None},
    ),
    (
        "installation_repositories-entry-without-id",
        "installation_repositories",
        {"action": "added", "repositories_added": [{"full_name": "drewjst/doug"}]},
    ),
]


@pytest.mark.parametrize(
    ("event", "payload"),
    [(event, payload) for _, event, payload in MALFORMED_DELIVERIES],
    ids=[label for label, _, _ in MALFORMED_DELIVERIES],
)
def test_a_signed_delivery_a_handler_cannot_use_is_202_and_writes_nothing(
    event, payload, tmp_path, monkeypatch
):
    """A handler must be total over its own payload, not total over the
    payloads GitHub sends today.

    These all carry a usable installation, so they are past the guard that
    makes installation["id"] safe and inside a handler. A KeyError or a
    TypeError here is a 500, GitHub redelivers a 500, and the redelivery has
    the same shape — so one reshaped, truncated or replayed delivery becomes
    a loop that never ends and never reviews anything. Missing facts have to
    fail a guard and be logged, which is what these assert: 202, and no row
    built out of a guess."""
    _hook_env(tmp_path, monkeypatch)
    r = _webhook(event, {**payload, "installation": INSTALLATION})
    assert r.status_code == 202
    assert _table(tmp_path, store.review_jobs) == []
    assert _table(tmp_path, store.outcome_jobs) == []
    assert _table(tmp_path, store.verdicts) == []
    assert _table(tmp_path, store.installation_repos) == []


def test_a_malformed_repo_entry_does_not_cost_the_repos_beside_it(tmp_path, monkeypatch):
    """One unusable entry drops itself, not the delivery. The installation
    genuinely covers the other repos in that list, and dropping all of them
    would take the healing path off every one — active_repos is what
    reconcile reads."""
    _hook_env(tmp_path, monkeypatch)
    r = _webhook(
        "installation",
        {
            "action": "created",
            "installation": INSTALLATION,
            "repositories": [
                {"id": 987, "full_name": "drewjst/doug"},
                {"id": None, "full_name": "drewjst/nameless"},
                {"full_name": "drewjst/idless"},
                "not-an-object",
                {"id": 988, "full_name": "drewjst/other"},
            ],
        },
    )
    assert r.status_code == 202
    repos = {r["github_repo_id"]: r for r in _table(tmp_path, store.installation_repos)}
    assert set(repos) == {987, 988}


def test_a_pull_request_carrying_neither_repo_id_is_not_enqueued(tmp_path, monkeypatch):
    """The fork gate compares ids; it must not compare two absences.

    `base.repo.id: null` with `head.repo: null` makes `head_id != base_id`
    False — None == None — so the payload that names no repo at all is the
    one shape that gets *through* the spend gate. What stops it after that
    is review_jobs.github_repo_id being NOT NULL, i.e. the insert raises and
    the delivery 500s into a redelivery loop; the queue's identity is those
    columns, so there was never a row for it to be. Non-int ids are a fork
    here for the same reason worker._skip_reason calls them one: the safe
    direction to be wrong in is skip."""
    _hook_env(tmp_path, monkeypatch)
    for base_id in (None, "987", {}):
        payload = _pr_payload(head_repo_id=None)
        payload["pull_request"]["base"]["repo"]["id"] = base_id
        assert _webhook("pull_request", payload).status_code == 202
    assert _table(tmp_path, store.review_jobs) == []


def test_a_pull_request_whose_draft_state_is_unknown_is_not_enqueued(tmp_path, monkeypatch):
    """An absent or non-boolean `draft` is an unknown state, and unknown
    skips — the same answer worker._skip_reason gives the same PR, whose
    docstring calls the two one gate. Reading a missing key as "not a draft"
    made them disagree: reconcile would decline to enqueue a PR the webhook
    had just paid to review."""
    _hook_env(tmp_path, monkeypatch)
    for draft in (None, "false", {}):
        payload = _pr_payload()
        payload["pull_request"]["draft"] = draft
        assert _webhook("pull_request", payload).status_code == 202
    del payload["pull_request"]["draft"]
    assert _webhook("pull_request", payload).status_code == 202
    assert _table(tmp_path, store.review_jobs) == []


def test_a_signed_body_that_is_not_json_is_ignored(tmp_path, monkeypatch):
    _hook_env(tmp_path, monkeypatch)
    body = b"not json"
    r = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": _sig(SECRET.encode(), body, "sha256"),
        },
    )
    assert r.status_code == 202


@pytest.mark.parametrize("body", [b"[1,2,3]", b"null", b'"a string"', b"7"])
def test_a_signed_body_that_is_json_but_not_an_object_is_ignored(
    body, tmp_path, monkeypatch
):
    """json.loads succeeds on all four, so none of them reaches the
    not-JSON branch — and every line after that branch is a dict lookup.
    `b"not json"` above is the one malformed shape that does NOT reach
    this, which is why it was not enough."""
    _hook_env(tmp_path, monkeypatch)
    r = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": _sig(SECRET.encode(), body, "sha256"),
        },
    )
    assert r.status_code == 202
    assert _table(tmp_path, store.review_jobs) == []


def test_an_action_that_is_not_a_string_is_ignored(tmp_path, monkeypatch):
    """The gating table is a set membership test, and an unhashable action
    raises TypeError before any handler is chosen — a 500 on the dispatch
    itself rather than inside a handler."""
    _hook_env(tmp_path, monkeypatch)
    for action in ({}, [], 7, None):
        payload = {"action": action, "installation": INSTALLATION}
        assert _webhook("pull_request", payload).status_code == 202
    assert _table(tmp_path, store.review_jobs) == []


def test_a_forged_signature_never_reaches_the_queue(tmp_path, monkeypatch):
    """The gating table is only worth anything behind verification. A
    valid-looking payload signed with the wrong key must 401 before any of
    it is parsed."""
    _hook_env(tmp_path, monkeypatch)
    r = _webhook("pull_request", _pr_payload(), secret="wrong-key")
    assert r.status_code == 401
    assert _table(tmp_path, store.review_jobs) == []


def test_the_webhook_refuses_when_there_is_no_ledger(tmp_path, monkeypatch):
    """A 202 means "queued". Without a database there is no queue: the
    installation writes would no-op silently and ingest.enqueue raises. The
    refusal is scoped to this endpoint because DATABASE_URL is optional for
    the rest of the service by design — /v1/score and the fixture-backed
    queue must keep working without one."""
    _hook_env(tmp_path, monkeypatch)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert _webhook("pull_request", _pr_payload()).status_code == 503


def test_the_ledger_check_does_not_run_on_the_event_loop_thread(tmp_path, monkeypatch):
    """store.enabled() is not the cheap read it looks like: on a cold engine
    store._get_engine() creates one, runs create_all() and applies
    migrations — a DDL round trip against Cloud SQL — and it takes a
    threading.Lock on every call, so the loop thread stalls behind any
    worker already inside it too. Left on the event loop thread it blocks
    every other in-flight delivery for the duration.

    The signature check is the marker for the loop thread rather than a
    hardcoded thread name: verify_webhook is deliberately there, being
    CPU-bound work on a body already in memory. Asserting the two ran on
    different threads is the property; which thread is an implementation
    detail of the server."""
    _hook_env(tmp_path, monkeypatch)
    seen: dict[str, str] = {}

    def _verify(secret, body, signature):
        seen["loop"] = threading.current_thread().name
        return True

    def _enabled():
        seen["ledger"] = threading.current_thread().name
        return True

    monkeypatch.setattr(api, "verify_webhook", _verify)
    monkeypatch.setattr(store, "enabled", _enabled)
    # A draft: past the ledger check, and it writes nothing.
    assert _webhook("pull_request", _pr_payload(draft=True)).status_code == 202
    assert seen["loop"] and seen["ledger"]
    assert seen["ledger"] != seen["loop"]


def test_ping_answers_even_without_a_ledger(monkeypatch):
    """The App's connectivity test is the first delivery a new install
    sends, and answering it 503 would read as "the webhook is broken" while
    pointing at the wrong thing."""
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert _webhook("ping", {"zen": "Speak like a human."}).status_code == 202


def test_comparisons_route_is_gone(monkeypatch):
    """Dual-run soak instrument retired with the CI path (PR #54)."""
    monkeypatch.setenv("DOUG_API_TOKEN", "secret")
    assert client.get(
        "/v1/comparisons", headers={"X-Doug-Token": "secret"}
    ).status_code == 404


def _api_db(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/doug.db")


def _pepper_env(monkeypatch):
    monkeypatch.setenv("DOUG_TOKEN_PEPPER", base64.b64encode(b"p" * 32).decode())


def _seed_verdict(*, repo, pr_number, installation_id, github_repo_id=None):
    store.save_review(
        repo, pr_number, "reader", VERDICT_FOR_QUEUE,
        pr_meta={**PR_META, "number": pr_number},
        installation_id=installation_id, github_repo_id=github_repo_id,
    )


def test_dispense_without_a_github_token_is_401(tmp_path, monkeypatch):
    _api_db(tmp_path, monkeypatch)
    r = client.post("/v1/installations/token", json={"repo": "drewjst/doug"})
    assert r.status_code == 401


def test_dispense_hides_every_verification_failure_behind_404(tmp_path, monkeypatch):
    """403 would confirm the repo exists. So would a distinct message for
    'not installed' versus 'not an admin'. One shape for all of them."""
    _api_db(tmp_path, monkeypatch)
    monkeypatch.setattr(tenancy, "verify_admin", lambda pat, owner, repo: None)
    r = client.post(
        "/v1/installations/token",
        json={"repo": "someone/private"},
        headers={"X-GitHub-Token": "ghp_x"},
    )
    assert r.status_code == 404


def test_dispense_404s_a_malformed_repo_without_calling_github(tmp_path, monkeypatch):
    _api_db(tmp_path, monkeypatch)
    calls = []

    def _spy(pat, owner, repo):
        calls.append((owner, repo))
        return 150424894

    monkeypatch.setattr(tenancy, "verify_admin", _spy)
    for bad in ("doug", "/doug", "drewjst/", ""):
        r = client.post(
            "/v1/installations/token",
            json={"repo": bad},
            headers={"X-GitHub-Token": "ghp_x"},
        )
        assert r.status_code == 404, bad
    # Over the per-mint repo cap: refused before it can spend a single
    # GitHub call proving any of the 21 repos — the cap check runs before
    # any proof, the same as a malformed name does.
    r = client.post(
        "/v1/installations/token",
        json={"selection": "selected", "repos": [f"o/r{i}" for i in range(21)]},
        headers={"X-GitHub-Token": "ghp_x"},
    )
    assert r.status_code == 404
    assert calls == []


def test_dispense_rejects_duplicate_repo_names_before_any_proof(tmp_path, monkeypatch):
    """Case-insensitive dedupe: GitHub treats repo names case-insensitively,
    so DrewJst/Doug and drewjst/doug collide on the same junction row. Left
    unchecked, mint_key would insert the key row and then 500 on
    set_installation_token_repos' uq_installation_token_repo — orphaning that
    key row with zero repos attached. Reject before spending anyone's GitHub
    quota proving either name."""
    _api_db(tmp_path, monkeypatch)
    _pepper_env(monkeypatch)
    store.upsert_installation(150424894, "drewjst", "User", "active")
    store.set_installation_repos(150424894, [(111, "drewjst/doug")], replace=False)
    calls = []
    monkeypatch.setattr(
        tenancy, "verify_admin",
        lambda pat, owner, repo: calls.append((owner, repo)) or 150424894,
    )
    r = client.post(
        "/v1/installations/token",
        json={"selection": "selected", "repos": ["drewjst/doug", "DrewJst/Doug"]},
        headers={"X-GitHub-Token": "ghp_x"},
    )
    assert r.status_code == 404
    assert calls == [], "duplicate names must not spend a single GitHub call"
    assert _table(tmp_path, store.installation_tokens) == [], "no orphaned key row"


def test_dispense_404s_when_verification_passes_but_no_installation_row(tmp_path, monkeypatch):
    """verify_org_admin says GitHub knows about the installation but the
    ledger does not — mint_key refuses, and so must the endpoint."""
    _api_db(tmp_path, monkeypatch)
    _pepper_env(monkeypatch)
    monkeypatch.setattr(tenancy, "verify_org_admin", lambda pat, owner: 999)
    monkeypatch.setattr(tenancy, "caller_login", lambda pat: "drewjst")
    r = client.post(
        "/v1/installations/token",
        json={"selection": "all", "owner": "drewjst"},
        headers={"X-GitHub-Token": "ghp_x"},
    )
    assert r.status_code == 404


def test_dispense_without_a_ledger_is_503(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    r = client.post(
        "/v1/installations/token",
        json={"repo": "drewjst/doug"},
        headers={"X-GitHub-Token": "ghp_x"},
    )
    assert r.status_code == 503


def test_dispense_selected_returns_a_key_scoped_to_the_named_repos(tmp_path, monkeypatch):
    _api_db(tmp_path, monkeypatch)
    _pepper_env(monkeypatch)
    store.upsert_installation(150424894, "drewjst", "User", "active")
    store.set_installation_repos(150424894, [(111, "drewjst/doug")], replace=False)
    monkeypatch.setattr(tenancy, "verify_repos_admin", lambda pat, repos: 150424894)
    monkeypatch.setattr(tenancy, "caller_login", lambda pat: "drewjst")
    r = client.post(
        "/v1/installations/token",
        json={"selection": "selected", "repos": ["drewjst/doug"], "label": "ci"},
        headers={"X-GitHub-Token": "ghp_x"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["token"].startswith("doug_live_")
    assert body["installation_id"] == 150424894
    assert body["selection"] == "selected"
    assert body["repos"] == ["drewjst/doug"]
    ctx = tenancy.resolve(body["token"])
    assert ctx.repo_ids == frozenset({111})


def test_dispense_all_requires_org_admin_proof(tmp_path, monkeypatch):
    _api_db(tmp_path, monkeypatch)
    _pepper_env(monkeypatch)
    store.upsert_installation(150424894, "acme", "Organization", "active")
    monkeypatch.setattr(tenancy, "verify_org_admin", lambda pat, owner: None)
    r = client.post(
        "/v1/installations/token",
        json={"selection": "all", "owner": "acme"},
        headers={"X-GitHub-Token": "ghp_x"},
    )
    assert r.status_code == 404, "failed proof is indistinguishable from absence"


def test_dispense_legacy_repo_body_still_mints_a_selected_key(tmp_path, monkeypatch):
    _api_db(tmp_path, monkeypatch)
    _pepper_env(monkeypatch)
    store.upsert_installation(150424894, "drewjst", "User", "active")
    store.set_installation_repos(150424894, [(111, "drewjst/doug")], replace=False)
    monkeypatch.setattr(tenancy, "verify_repos_admin", lambda pat, repos: 150424894)
    monkeypatch.setattr(tenancy, "caller_login", lambda pat: "drewjst")
    r = client.post(
        "/v1/installations/token",
        json={"repo": "drewjst/doug"},
        headers={"X-GitHub-Token": "ghp_x"},
    )
    assert r.status_code == 200
    assert r.json()["selection"] == "selected"


def test_dispense_never_rotates_an_existing_key(tmp_path, monkeypatch):
    """The other half of MT5: repeat mints append; the first key keeps
    resolving. (Replaces test_minting_again_invalidates_the_previous_token,
    whose behavior was the bug.)"""
    _api_db(tmp_path, monkeypatch)
    _pepper_env(monkeypatch)
    store.upsert_installation(150424894, "drewjst", "User", "active")
    monkeypatch.setattr(tenancy, "verify_org_admin", lambda pat, owner: 150424894)
    monkeypatch.setattr(tenancy, "caller_login", lambda pat: "drewjst")
    body = {"selection": "all", "owner": "drewjst"}
    headers = {"X-GitHub-Token": "t"}
    first = client.post("/v1/installations/token", json=body, headers=headers).json()
    second = client.post("/v1/installations/token", json=body, headers=headers).json()
    assert first["token"] != second["token"]
    assert tenancy.resolve(first["token"]) is not None
    assert tenancy.resolve(second["token"]) is not None


def test_dispense_daily_cap_is_fail_open(tmp_path, monkeypatch):
    _api_db(tmp_path, monkeypatch)
    _pepper_env(monkeypatch)
    store.upsert_installation(150424894, "drewjst", "User", "active")
    monkeypatch.setattr(tenancy, "verify_org_admin", lambda pat, owner: 150424894)
    monkeypatch.setattr(tenancy, "caller_login", lambda pat: "drewjst")
    body = {"selection": "all", "owner": "drewjst"}
    headers = {"X-GitHub-Token": "t"}
    # Over the cap → 404 (uniform).
    monkeypatch.setattr(store, "count_installation_tokens_minted_since", lambda i, s: 30)
    assert client.post("/v1/installations/token", json=body, headers=headers).status_code == 404
    # Counter broken → None → allow (fail-open by spec).
    monkeypatch.setattr(store, "count_installation_tokens_minted_since", lambda i, s: None)
    assert client.post("/v1/installations/token", json=body, headers=headers).status_code == 200


def test_dispense_validation_is_uniform_404(tmp_path, monkeypatch):
    _api_db(tmp_path, monkeypatch)
    _pepper_env(monkeypatch)
    store.upsert_installation(150424894, "drewjst", "User", "active")
    headers = {"X-GitHub-Token": "t"}
    for bad in (
        {"selection": "all"},                                  # no owner
        {"selection": "selected", "repos": []},                # empty selection
        {"selection": "selected", "repos": ["notaslash"]},     # malformed repo
        {"selection": "selected", "repos": [f"o/r{i}" for i in range(21)]},  # over cap
        {"selection": "all", "owner": "acme", "expires_in_days": 400},       # out of range
    ):
        r = client.post("/v1/installations/token", json=bad, headers=headers)
        assert r.status_code == 404, bad


def test_dispense_expires_in_days_is_wired_into_the_response(tmp_path, monkeypatch):
    """Pins that body.expires_in_days actually reaches mint_key and comes
    back out on the response, not just that the field round-trips."""
    _api_db(tmp_path, monkeypatch)
    _pepper_env(monkeypatch)
    store.upsert_installation(150424894, "drewjst", "User", "active")
    monkeypatch.setattr(tenancy, "verify_org_admin", lambda pat, owner: 150424894)
    monkeypatch.setattr(tenancy, "caller_login", lambda pat: "drewjst")
    r = client.post(
        "/v1/installations/token",
        json={"selection": "all", "owner": "drewjst", "expires_in_days": 90},
        headers={"X-GitHub-Token": "t"},
    )
    assert r.status_code == 200
    expires_at = datetime.fromisoformat(r.json()["expires_at"])
    delta = expires_at - datetime.now(UTC)
    assert timedelta(days=85) < delta < timedelta(days=95)


def test_dispense_selected_repo_lookup_is_case_insensitive(tmp_path, monkeypatch):
    """GitHub-proved admins must not 404 on a ledger entry that merely
    differs in case: GitHub repo names are case-insensitive, so the
    active_repos lookup keying the mint's repo_ids must be too."""
    _api_db(tmp_path, monkeypatch)
    _pepper_env(monkeypatch)
    store.upsert_installation(150424894, "drewjst", "User", "active")
    store.set_installation_repos(150424894, [(111, "DrewJst/Doug")], replace=False)
    monkeypatch.setattr(tenancy, "verify_repos_admin", lambda pat, repos: 150424894)
    monkeypatch.setattr(tenancy, "caller_login", lambda pat: "drewjst")
    r = client.post(
        "/v1/installations/token",
        json={"selection": "selected", "repos": ["drewjst/doug"]},
        headers={"X-GitHub-Token": "ghp_x"},
    )
    assert r.status_code == 200
    ctx = tenancy.resolve(r.json()["token"])
    assert ctx.repo_ids == frozenset({111})


def test_dispense_without_pepper_is_503(tmp_path, monkeypatch):
    _api_db(tmp_path, monkeypatch)
    monkeypatch.delenv("DOUG_TOKEN_PEPPER", raising=False)
    store.upsert_installation(150424894, "drewjst", "User", "active")
    monkeypatch.setattr(tenancy, "verify_org_admin", lambda pat, owner: 150424894)
    monkeypatch.setattr(tenancy, "caller_login", lambda pat: "drewjst")
    r = client.post(
        "/v1/installations/token",
        json={"selection": "all", "owner": "drewjst"},
        headers={"X-GitHub-Token": "t"},
    )
    assert r.status_code == 503


def test_dispense_response_and_logs_never_carry_the_secret_twice(tmp_path, monkeypatch, capsys):
    """Show-once: the token appears in the response body and NOWHERE else —
    not in stderr, where every other diagnostic in this app writes."""
    _api_db(tmp_path, monkeypatch)
    _pepper_env(monkeypatch)
    store.upsert_installation(150424894, "drewjst", "User", "active")
    monkeypatch.setattr(tenancy, "verify_org_admin", lambda pat, owner: 150424894)
    monkeypatch.setattr(tenancy, "caller_login", lambda pat: "drewjst")
    r = client.post(
        "/v1/installations/token",
        json={"selection": "all", "owner": "drewjst"},
        headers={"X-GitHub-Token": "t"},
    )
    token = r.json()["token"]
    from doug import keyformat
    secret = keyformat.parse(token).secret
    err = capsys.readouterr().err
    assert token not in err and secret not in err


def _tenant(tmp_path, monkeypatch, installation_id=150424894, login="drewjst"):
    _api_db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_API_TOKEN", "operator-secret")
    _pepper_env(monkeypatch)
    store.upsert_installation(installation_id, login, "User", "active")
    minted = tenancy.mint_key(
        installation_id, repo_selection="all", repo_ids=[], label=None,
        expires_in_days=0, minted_by=login,
    )
    return minted.token


def test_tenant_token_sees_only_its_own_rows(tmp_path, monkeypatch):
    token = _tenant(tmp_path, monkeypatch)
    # An 'all' key's row filter now runs on live installation_repos ids (MT4),
    # so the repo must be registered and the verdict carry a matching id —
    # exactly what the real ingest path (worker.py) always writes together.
    store.set_installation_repos(150424894, [(1, "drewjst/doug")], replace=False)
    _seed_verdict(repo="drewjst/doug", pr_number=1, installation_id=150424894, github_repo_id=1)
    # Same github_repo_id as the tenant's own live repo, on a different
    # installation: this is the reachable window the installation filter
    # alone must close (id-scope can't, since the id collides) — the same
    # repo id can be active under two installations mid-transfer, or after a
    # missed repositories_removed delivery leaves the old owner's row stale.
    _seed_verdict(repo="someone/else", pr_number=2, installation_id=777, github_repo_id=1)
    r = client.get("/v1/queue", headers={"X-Doug-Token": token})
    assert r.status_code == 200
    # PRMetadata carries no `repo` field, so the returned row is identified by
    # the url _with_url back-fills from the ledger's repo + pr_number columns.
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["pr"]["url"] == "https://github.com/drewjst/doug/pull/1"


def test_operator_token_still_sees_every_row(tmp_path, monkeypatch):
    """No soak regression: doug-web and the dual-run comparison both read
    through this path with the operator token."""
    _tenant(tmp_path, monkeypatch)
    _seed_verdict(repo="drewjst/doug", pr_number=1, installation_id=150424894)
    _seed_verdict(repo="someone/else", pr_number=2, installation_id=777)
    r = client.get("/v1/queue", headers={"X-Doug-Token": "operator-secret"})
    assert r.status_code == 200
    assert len(r.json()["items"]) == 2


def test_cross_tenant_repo_is_404_not_an_empty_list(tmp_path, monkeypatch):
    """The M2 exit gate, pinned. An empty list would be indistinguishable
    from 'no reviews yet', which tells the caller their guess might be a
    real repo. 404 says nothing at all."""
    token = _tenant(tmp_path, monkeypatch)
    store.set_installation_repos(150424894, [(1, "drewjst/doug")], replace=True)
    r = client.get("/v1/queue", params={"repo": "someone/else"}, headers={"X-Doug-Token": token})
    assert r.status_code == 404


def test_in_scope_repo_filters_normally(tmp_path, monkeypatch):
    token = _tenant(tmp_path, monkeypatch)
    store.set_installation_repos(150424894, [(1, "drewjst/doug")], replace=True)
    # MT4: the row filter now keys on this same live id, not just the name.
    _seed_verdict(repo="drewjst/doug", pr_number=1, installation_id=150424894, github_repo_id=1)
    r = client.get("/v1/queue", params={"repo": "drewjst/doug"}, headers={"X-Doug-Token": token})
    assert r.status_code == 200
    assert len(r.json()["items"]) == 1


def test_queue_refuses_a_key_lacking_queue_read_scope(tmp_path, monkeypatch):
    """Every key mints with queue:read today (see test_operator_token_still_
    sees_every_row for the pass side on a normal key), but the scopes column
    is the real gate: a key stripped of it — or minted for something else
    entirely, like a future receipts/MCP scope — must not read the queue."""
    token = _tenant(tmp_path, monkeypatch)
    from doug import keyformat
    parsed = keyformat.parse(token)
    row = store.installation_token_by_lookup(parsed.lookup)
    engine = store._get_engine()
    with engine.begin() as conn:
        conn.execute(
            store.installation_tokens.update()
            .where(store.installation_tokens.c.id == row["id"])
            .values(scopes=["receipts:read"])
        )
    r = client.get("/v1/queue", headers={"X-Doug-Token": token})
    assert r.status_code == 401


def test_unknown_token_is_401(tmp_path, monkeypatch):
    _tenant(tmp_path, monkeypatch)
    r = client.get("/v1/queue", headers={"X-Doug-Token": "doug_nope"})
    assert r.status_code == 401


def test_queue_selected_key_sees_only_its_repos_rows(tmp_path, monkeypatch):
    """MT1 at read time: a repo-scoped key must not read sibling repos'
    verdicts even inside its own installation."""
    _api_db(tmp_path, monkeypatch)
    _pepper_env(monkeypatch)
    monkeypatch.setenv("DOUG_API_TOKEN", "operator")
    store.upsert_installation(150424894, "drewjst", "User", "active")
    store.set_installation_repos(
        150424894, [(111, "drewjst/a"), (222, "drewjst/b")], replace=False
    )
    _seed_verdict(repo="drewjst/a", github_repo_id=111, installation_id=150424894, pr_number=1)
    _seed_verdict(repo="drewjst/b", github_repo_id=222, installation_id=150424894, pr_number=2)
    minted = tenancy.mint_key(
        150424894, repo_selection="selected", repo_ids=[111], label=None,
        expires_in_days=0, minted_by="drewjst",
    )
    r = client.get("/v1/queue", headers={"x-doug-token": minted.token})
    assert r.status_code == 200
    # PRMetadata carries no `repo` field; identify rows by the URL _with_url
    # back-fills from the ledger's repo + pr_number columns.
    urls_seen = {item["pr"]["url"] for item in r.json()["items"]}
    assert urls_seen == {"https://github.com/drewjst/a/pull/1"}


def test_repo_param_outside_the_keys_selection_is_404_not_empty(tmp_path, monkeypatch):
    """Slice A left a gap on purpose: a selected key naming a sibling ACTIVE
    repo passed the name check and got an empty list — which confirms the
    repo exists. MT4's id-unification closes it to a 404."""
    _api_db(tmp_path, monkeypatch)
    _pepper_env(monkeypatch)
    monkeypatch.setenv("DOUG_API_TOKEN", "operator")
    store.upsert_installation(150424894, "drewjst", "User", "active")
    store.set_installation_repos(
        150424894, [(111, "drewjst/a"), (222, "drewjst/b")], replace=False
    )
    minted = tenancy.mint_key(
        150424894, repo_selection="selected", repo_ids=[111], label=None,
        expires_in_days=0, minted_by="drewjst",
    )
    r = client.get(
        "/v1/queue", params={"repo": "drewjst/b"}, headers={"x-doug-token": minted.token}
    )
    assert r.status_code == 404


def test_queue_rows_and_repo_check_share_one_source_of_truth(tmp_path, monkeypatch):
    """MT4's consistency property, pinned: any repo the unfiltered queue
    returns rows for, ?repo= must accept — and vice versa. The old shape
    (names for the check, installation_id for the rows) could disagree."""
    _api_db(tmp_path, monkeypatch)
    _pepper_env(monkeypatch)
    monkeypatch.setenv("DOUG_API_TOKEN", "operator")
    store.upsert_installation(150424894, "drewjst", "User", "active")
    store.set_installation_repos(150424894, [(111, "drewjst/a")], replace=False)
    # The live repo's own verdict — without this, repos_served is empty and
    # the loop below never runs, proving nothing.
    _seed_verdict(repo="drewjst/a", github_repo_id=111, installation_id=150424894, pr_number=1)
    # A verdict for a repo the installation no longer covers (state flip):
    _seed_verdict(repo="drewjst/gone", github_repo_id=333, installation_id=150424894, pr_number=9)
    minted = tenancy.mint_key(
        150424894, repo_selection="all", repo_ids=[], label=None,
        expires_in_days=0, minted_by="drewjst",
    )
    unfiltered = client.get("/v1/queue", headers={"x-doug-token": minted.token}).json()
    # PRMetadata carries no `repo` field; identify rows by the URL _with_url
    # back-fills from the ledger's repo + pr_number columns.
    repos_served = {
        item["pr"]["url"].removeprefix("https://github.com/").rsplit("/pull/", 1)[0]
        for item in unfiltered["items"]
    }
    # Proves the served side: the live repo is in, the removed one is out —
    # the row filter already agrees with installation_repos on its own.
    assert repos_served == {"drewjst/a"}
    # Proves the acceptance side: what the unfiltered queue serves, ?repo=
    # must accept too (vacuous now that repos_served is non-empty).
    for full_name in repos_served:
        assert (
            client.get(
                "/v1/queue", params={"repo": full_name},
                headers={"x-doug-token": minted.token},
            ).status_code == 200
        ), f"unfiltered queue served {full_name} but ?repo= refuses it"


def test_queue_operator_repo_filter_reaches_store_as_a_name(tmp_path, monkeypatch):
    """The operator's ?repo= is a NAME lookup across every installation, and
    only the operator may reach it. Operator-ness must be an explicit flag
    (is_operator), not the absence of a TokenContext — a future credential
    type that never produces a ctx must not silently inherit this."""
    _api_db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_API_TOKEN", "operator-secret")
    calls: list[dict] = []
    real = store.latest_reviews

    def spy(**kwargs):
        calls.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(store, "latest_reviews", spy)
    r = client.get(
        "/v1/queue", params={"repo": "drewjst/doug"},
        headers={"X-Doug-Token": "operator-secret"},
    )
    assert r.status_code == 200
    assert calls == [{"repo": "drewjst/doug", "installation_id": None, "repo_ids": None}]


def test_queue_tenant_repo_restriction_never_reaches_store_as_a_name(tmp_path, monkeypatch):
    """A resolved tenant token's repo restriction must arrive as repo_ids —
    scoped ids checked against the key's live selection — and NEVER as the
    `repo=` name lookup, which searches every installation. Pins the fix at
    api.py:428: `repo=repo if is_operator else None` must stay tied to the
    explicit operator flag, not to `ctx is None`."""
    token = _tenant(tmp_path, monkeypatch)
    store.set_installation_repos(150424894, [(1, "drewjst/doug")], replace=True)
    _seed_verdict(repo="drewjst/doug", pr_number=1, installation_id=150424894, github_repo_id=1)
    calls: list[dict] = []
    real = store.latest_reviews

    def spy(**kwargs):
        calls.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(store, "latest_reviews", spy)
    r = client.get(
        "/v1/queue", params={"repo": "drewjst/doug"}, headers={"X-Doug-Token": token},
    )
    assert r.status_code == 200
    assert calls == [{"repo": None, "installation_id": 150424894, "repo_ids": frozenset({1})}]


def test_queue_unresolvable_token_401s_before_touching_store(tmp_path, monkeypatch):
    """A caller who is neither the operator nor a resolvable token must 401
    and never reach store.latest_reviews at all — this pins api.py:400,
    which must stay untouched by the is_operator refactor (it means 'this
    token did not resolve', not 'this caller is the operator')."""
    _tenant(tmp_path, monkeypatch)
    calls: list[dict] = []

    def spy(**kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(store, "latest_reviews", spy)
    r = client.get("/v1/queue", headers={"X-Doug-Token": "doug_nope"})
    assert r.status_code == 401
    assert calls == []


def test_queue_latest_reviews_call_site_keys_the_repo_filter_on_is_operator():
    """Narrow structural pin on ONLY the store.latest_reviews call site's
    `repo=` argument — not a substring search over the whole function body,
    which legitimately still contains `ctx is None` at api.py:400 (an
    unresolved-token check, not an operator check).

    This guard exists because, with exactly one credential type in the
    system today, `ctx is None` and `is_operator` are PROVABLY behaviourally
    identical at this call site (ctx is only ever assigned inside the
    `not is_operator` branch, and unresolved tokens 401 before reaching this
    line) — so no behavioural test, however thorough, can distinguish a
    regression back to `repo=repo if ctx is None else None` from the fixed
    `is_operator` form. Confirmed by temporarily reverting the call site and
    re-running the behavioural tests above: they stayed green. Task 4 adding
    a second credential type is exactly what would make that regression
    observable behaviourally — this guard stands in until then.
    """
    src = inspect.getsource(api.queue)
    start = src.index("store.latest_reviews(")
    call = src[start : src.index(")", start)]
    repo_line = next(line for line in call.splitlines() if "repo=" in line)
    assert repo_line.strip().startswith("repo=repo if is_operator else None")


@pytest.mark.parametrize("path", ["/v1/patterns", "/v1/score/read", "/v1/runs", "/v1/runs/1"])
def test_tenant_token_404s_on_operator_only_endpoints(tmp_path, monkeypatch, path):
    """A valid credential pointed at an endpoint that is not theirs learns
    only that there is nothing there — same no-existence-leak rule as a
    cross-tenant repo."""
    token = _tenant(tmp_path, monkeypatch)
    call = client.post if path == "/v1/score/read" else client.get
    # A VALID ReadScoreRequest body ({pr, diff}) — FastAPI validates the body
    # before the handler runs, so a malformed one 422s and the test would
    # never reach the auth gate it exists to check.
    body = {"pr": {"number": 1, "title": "x", "author": "dev"}, "diff": ""}
    kwargs = {"json": body} if path == "/v1/score/read" else {}
    r = call(path, headers={"X-Doug-Token": token}, **kwargs)
    assert r.status_code == 404


@pytest.mark.parametrize("path", ["/v1/patterns", "/v1/runs", "/v1/runs/1"])
def test_junk_token_is_still_401_on_operator_only_endpoints(tmp_path, monkeypatch, path):
    _tenant(tmp_path, monkeypatch)
    r = client.get(path, headers={"X-Doug-Token": "doug_nope"})
    assert r.status_code == 401


def test_queue_without_operator_token_configured_is_503(tmp_path, monkeypatch):
    """A missing operator secret is a deployment misconfiguration and must
    fail loudly, not be masked by tenant traffic that happens to work."""
    _api_db(tmp_path, monkeypatch)
    monkeypatch.delenv("DOUG_API_TOKEN", raising=False)
    _pepper_env(monkeypatch)
    store.upsert_installation(150424894, "drewjst", "User", "active")
    minted = tenancy.mint_key(
        150424894, repo_selection="all", repo_ids=[], label=None,
        expires_in_days=0, minted_by="drewjst",
    )
    r = client.get("/v1/queue", headers={"X-Doug-Token": minted.token})
    assert r.status_code == 503


def test_list_tokens_requires_org_admin_and_masks(tmp_path, monkeypatch):
    _api_db(tmp_path, monkeypatch)
    _pepper_env(monkeypatch)
    store.upsert_installation(150424894, "drewjst", "User", "active")
    minted = tenancy.mint_key(
        150424894, repo_selection="all", repo_ids=[], label="dash",
        expires_in_days=0, minted_by="drewjst",
    )
    # A second, pre-revoked key: the list is an audit trail, so a dead key
    # must stay visible (with a non-null revoked_at) beside the live one.
    revoked = tenancy.mint_key(
        150424894, repo_selection="all", repo_ids=[], label="old-ci",
        expires_in_days=0, minted_by="drewjst",
    )
    assert store.revoke_installation_token(revoked.token_id, 150424894)
    monkeypatch.setattr(tenancy, "verify_org_admin", lambda pat, owner: None)
    assert client.get(
        "/v1/installations/tokens", params={"owner": "drewjst"},
        headers={"X-GitHub-Token": "t"},
    ).status_code == 404
    monkeypatch.setattr(tenancy, "verify_org_admin", lambda pat, owner: 150424894)
    r = client.get(
        "/v1/installations/tokens", params={"owner": "drewjst"},
        headers={"X-GitHub-Token": "t"},
    )
    assert r.status_code == 200
    rows = r.json()["tokens"]
    assert len(rows) == 2
    by_id = {row["id"]: row for row in rows}
    assert by_id[minted.token_id]["label"] == "dash"
    assert by_id[minted.token_id]["last4"] == minted.last4
    assert by_id[minted.token_id]["revoked_at"] is None
    assert by_id[revoked.token_id]["label"] == "old-ci"
    assert by_id[revoked.token_id]["revoked_at"] is not None
    body = r.text
    assert minted.token not in body and revoked.token not in body and "token_hash" not in body


def test_management_endpoints_reject_doug_tokens_as_proof(tmp_path, monkeypatch):
    """Keys cannot manage keys: a leaked key must never outrun revocation.
    Management proof is a GitHub PAT, full stop.

    _caller_client is monkeypatched to raise rather than letting a doug
    token attempt a real GitHub call: that call would fail anyway (a doug
    key is not a usable PAT), but leaving it unmocked makes the test's
    outcome and timing depend on the sandbox's network reachability rather
    than on the code under test. Patching _caller_client (not caller_login
    itself) keeps caller_login's own try/except in the loop, so the failure
    still flows through the exact exception-to-None path a real network
    failure would take.
    """
    _api_db(tmp_path, monkeypatch)
    _pepper_env(monkeypatch)
    store.upsert_installation(150424894, "drewjst", "User", "active")
    minted = tenancy.mint_key(
        150424894, repo_selection="all", repo_ids=[], label=None,
        expires_in_days=0, minted_by="drewjst",
    )

    def _boom(pat):
        raise RuntimeError("a doug key is not a usable GitHub PAT")

    monkeypatch.setattr(tenancy, "_caller_client", _boom)
    r = client.get(
        "/v1/installations/tokens", params={"owner": "drewjst"},
        headers={"X-GitHub-Token": minted.token},  # a doug key is not a PAT
    )
    assert r.status_code == 404  # verify_org_admin fails on it upstream


def test_revoke_org_admin_can_kill_anything(tmp_path, monkeypatch):
    _api_db(tmp_path, monkeypatch)
    _pepper_env(monkeypatch)
    store.upsert_installation(150424894, "drewjst", "User", "active")
    minted = tenancy.mint_key(
        150424894, repo_selection="all", repo_ids=[], label=None,
        expires_in_days=0, minted_by="drewjst",
    )
    monkeypatch.setattr(tenancy, "verify_org_admin", lambda pat, owner: 150424894)
    r = client.delete(
        f"/v1/installations/token/{minted.token_id}", params={"owner": "drewjst"},
        headers={"X-GitHub-Token": "t"},
    )
    assert r.status_code == 200 and r.json()["revoked"] is True
    assert tenancy.resolve(minted.token) is None, "revocation is next-request effective"


def test_revoke_org_admin_can_kill_a_selected_key(tmp_path, monkeypatch):
    """Org-admin proof is not limited to 'all' keys — it revokes anything,
    a 'selected' key included."""
    _api_db(tmp_path, monkeypatch)
    _pepper_env(monkeypatch)
    store.upsert_installation(150424894, "drewjst", "User", "active")
    store.set_installation_repos(150424894, [(111, "drewjst/a")], replace=False)
    minted = tenancy.mint_key(
        150424894, repo_selection="selected", repo_ids=[111], label=None,
        expires_in_days=0, minted_by="drewjst",
    )
    monkeypatch.setattr(tenancy, "verify_org_admin", lambda pat, owner: 150424894)
    r = client.delete(
        f"/v1/installations/token/{minted.token_id}", params={"owner": "drewjst"},
        headers={"X-GitHub-Token": "t"},
    )
    assert r.status_code == 200 and r.json()["revoked"] is True
    assert tenancy.resolve(minted.token) is None


def test_revoke_repo_admin_must_cover_the_keys_selection(tmp_path, monkeypatch):
    _api_db(tmp_path, monkeypatch)
    _pepper_env(monkeypatch)
    store.upsert_installation(150424894, "drewjst", "User", "active")
    store.set_installation_repos(
        150424894, [(111, "drewjst/a"), (222, "drewjst/b")], replace=False
    )
    minted = tenancy.mint_key(
        150424894, repo_selection="selected", repo_ids=[111, 222], label=None,
        expires_in_days=0, minted_by="drewjst",
    )
    monkeypatch.setattr(tenancy, "verify_org_admin", lambda pat, owner: None)
    monkeypatch.setattr(tenancy, "verify_repos_admin", lambda pat, repos: 150424894)
    # Proof covers only repo a → does not cover {a, b} → 404.
    r = client.delete(
        f"/v1/installations/token/{minted.token_id}", params={"repos": "drewjst/a"},
        headers={"X-GitHub-Token": "t"},
    )
    assert r.status_code == 404
    # Proof covers both → revoked.
    r = client.delete(
        f"/v1/installations/token/{minted.token_id}", params={"repos": "drewjst/a,drewjst/b"},
        headers={"X-GitHub-Token": "t"},
    )
    assert r.status_code == 200
    # A foreign token id under valid proof: same 404 as absence.
    r = client.delete(
        "/v1/installations/token/999999", params={"repos": "drewjst/a,drewjst/b"},
        headers={"X-GitHub-Token": "t"},
    )
    assert r.status_code == 404


def test_revoke_repo_admin_cannot_kill_an_all_selection_key(tmp_path, monkeypatch):
    """Killing the org-wide key takes org-admin proof, full stop — even a
    FULLY COVERING, valid repo-admin proof must not reach it. An 'all' key
    has no junction rows, so repo-admin proof (which can only ever prove
    coverage of named repos) has nothing to intersect against. The second
    assertion pins that a refused attempt revokes nothing: no half-revoke
    on a wrong-proof-type request."""
    _api_db(tmp_path, monkeypatch)
    _pepper_env(monkeypatch)
    store.upsert_installation(150424894, "drewjst", "User", "active")
    store.set_installation_repos(150424894, [(111, "drewjst/a")], replace=False)
    minted = tenancy.mint_key(
        150424894, repo_selection="all", repo_ids=[], label=None,
        expires_in_days=0, minted_by="drewjst",
    )
    monkeypatch.setattr(tenancy, "verify_repos_admin", lambda pat, repos: 150424894)
    r = client.delete(
        f"/v1/installations/token/{minted.token_id}", params={"repos": "drewjst/a"},
        headers={"X-GitHub-Token": "t"},
    )
    assert r.status_code == 404
    assert tenancy.resolve(minted.token) is not None, "must not be half-revoked"


def test_revoke_repo_admin_lookup_is_case_insensitive(tmp_path, monkeypatch):
    """Mirrors dispense's by_name case fix: a proven owner/Repo must still
    match a ledger entry that only differs in case."""
    _api_db(tmp_path, monkeypatch)
    _pepper_env(monkeypatch)
    store.upsert_installation(150424894, "drewjst", "User", "active")
    store.set_installation_repos(150424894, [(111, "DrewJst/Doug")], replace=False)
    minted = tenancy.mint_key(
        150424894, repo_selection="selected", repo_ids=[111], label=None,
        expires_in_days=0, minted_by="drewjst",
    )
    monkeypatch.setattr(tenancy, "verify_org_admin", lambda pat, owner: None)
    monkeypatch.setattr(tenancy, "verify_repos_admin", lambda pat, repos: 150424894)
    r = client.delete(
        f"/v1/installations/token/{minted.token_id}", params={"repos": "drewjst/doug"},
        headers={"X-GitHub-Token": "t"},
    )
    assert r.status_code == 200 and r.json()["revoked"] is True


def test_revoke_malformed_owner_never_falls_through_to_the_repos_proof(
    tmp_path, monkeypatch
):
    """A present owner is authoritative even when malformed. Before this pin,
    owner="acme/x" silently yielded to the repos branch, so precedence
    flipped on a typo — an incident responder who fat-fingers the org gets
    whatever the repos param happens to authorize instead of a refusal
    (Doug's own review of PR #50, low finding 4)."""
    _api_db(tmp_path, monkeypatch)
    _pepper_env(monkeypatch)
    store.upsert_installation(150424894, "drewjst", "User", "active")
    store.set_installation_repos(150424894, [(111, "drewjst/doug")], replace=False)
    minted = tenancy.mint_key(
        150424894, repo_selection="selected", repo_ids=[111], label=None,
        expires_in_days=0, minted_by="drewjst",
    )
    # The repos proof WOULD succeed — which is exactly why the malformed
    # owner must refuse before that branch is ever considered.
    monkeypatch.setattr(tenancy, "verify_repos_admin", lambda pat, repos: 150424894)
    r = client.delete(
        f"/v1/installations/token/{minted.token_id}",
        params={"owner": "drewjst/doug", "repos": "drewjst/doug"},
        headers={"X-GitHub-Token": "t"},
    )
    assert r.status_code == 404
    assert tenancy.resolve(minted.token) is not None, "nothing may be revoked on the way out"


def test_uninstall_webhook_bulk_revokes_keys(tmp_path, monkeypatch):
    """resolve already fails on state='deleted' (MT2's live check). The bulk
    stamp is belt-and-braces AND the audit trail: revoked_at answers 'when
    did these keys die' after a reinstall flips state back to active —
    without it, an old key would resurrect on reinstall."""
    _api_db(tmp_path, monkeypatch)
    _pepper_env(monkeypatch)
    store.upsert_installation(150424894, "drewjst", "User", "active")
    minted = tenancy.mint_key(
        150424894, repo_selection="all", repo_ids=[], label=None,
        expires_in_days=0, minted_by="drewjst",
    )
    from doug.api import _record_installation
    _record_installation({"installation": {"id": 150424894, "account": {}}}, "deleted")
    # Reinstall: state flips back to active — the key must STAY dead.
    _record_installation({"installation": {"id": 150424894, "account": {}}}, "created")
    assert tenancy.resolve(minted.token) is None


# /v1/runs — the console's cross-installation verdict history. Same _db/AUTH/
# VERDICT shape test_store.py's run_history tests use: a token-gated route
# needs both a ledger and DOUG_API_TOKEN, and _db sets both because every
# test below calls it.
VERDICT = Verdict(
    score=0.62,
    band=Band.FLAGGED,
    threshold=0.30,
    reasons=[Reason(rule="reader:race-condition", label="Cache write is not guarded", weight=0.0)],
)

AUTH = {"X-Doug-Token": "t0ken"}


def _db(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path}/doug.db"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DOUG_API_TOKEN", "t0ken")
    return url


def test_runs_refuses_without_the_operator_token(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    client = TestClient(app)
    assert client.get("/v1/runs").status_code == 401


def test_runs_404s_a_tenant_key(tmp_path, monkeypatch):
    """A resolving tenant key is a real credential at the wrong door, so it
    gets the same no-existence-leak 404 _operator_only gives everywhere."""
    _db(tmp_path, monkeypatch)
    monkeypatch.setattr(tenancy, "resolve", lambda t: tenancy.TokenContext(
        installation_id=99, token_id=1, repo_ids=None, scopes=("queue:read",),
    ))
    client = TestClient(app)
    assert client.get("/v1/runs", headers={"X-Doug-Token": "dg_tenant"}).status_code == 404


def test_runs_returns_repo_and_installation_on_every_item(tmp_path, monkeypatch):
    """The fields /v1/queue drops. Without them the console cannot group
    per repo, which is the gap this endpoint exists to close."""
    _db(tmp_path, monkeypatch)
    store.save_review(
        "o/r", 7, "reader", VERDICT,
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    client = TestClient(app)
    item = client.get("/v1/runs", headers=AUTH).json()["items"][0]
    assert item["repo"] == "o/r"
    assert item["installation_id"] == 99
    assert item["verdict_id"] > 0


def test_runs_serialises_a_missing_read_as_null_not_zero(tmp_path, monkeypatch):
    """A deterministic run had no read. Zero coverage would claim Doug read
    nothing of a diff it never opened — empty is not zero."""
    _db(tmp_path, monkeypatch)
    store.save_review(
        "o/r", 7, "deterministic", VERDICT,
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    client = TestClient(app)
    assert client.get("/v1/runs", headers=AUTH).json()["items"][0]["coverage"] is None


def test_runs_rejects_an_out_of_range_limit(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    client = TestClient(app)
    assert client.get("/v1/runs?limit=0", headers=AUTH).status_code == 422
    assert client.get("/v1/runs?limit=501", headers=AUTH).status_code == 422


def test_runs_503s_without_a_ledger(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DOUG_API_TOKEN", "t0ken")
    client = TestClient(app)
    assert client.get("/v1/runs", headers=AUTH).status_code == 503


# Beyond the brief's six: the response is the contract Task 7's console
# reads, and none of those six touch title/url/tier/source/score/band/
# threshold/changed_files/finding_counts/job/outcome_14/pr_number/
# github_repo_id — a dropped or misspelled key among them would pass all
# six anyway. This pins every key of RunSummaryItem in one row that carries
# a real pr_meta, coverage, job and outcome.
def test_runs_serialises_every_key_of_the_response_contract(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    coverage = api.reader.Coverage(
        diff_chars=100, sent_chars=80, files_sent=2,
        files_unseen=["b.py"], file_cut="a.py",
    )
    pr_meta = {
        "number": 7, "title": "Add cache", "author": "dev", "files": ["a.py"],
        "url": "https://github.com/o/r/pull/7", "changed_files": 12,
    }
    vid = store.save_review(
        "o/r", 7, "reader", VERDICT,
        pr_meta=pr_meta, coverage=coverage,
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    engine = store._get_engine()
    with engine.begin() as conn:
        conn.execute(store.review_jobs.insert().values(
            installation_id=99, github_repo_id=1, repo_full_name="o/r",
            pr_number=7, head_sha="a" * 40, status="done", attempts=1,
            enqueued_at=datetime(2026, 8, 1, tzinfo=UTC),
            finished_at=datetime(2026, 8, 1, 0, 0, 5, tzinfo=UTC),
            verdict_id=vid,
        ))
        conn.execute(store.outcomes.insert().values(
            repo="o/r", pr_number=7, kind="clean", window_days=14,
            observed_at=datetime(2026, 8, 15, tzinfo=UTC), source="git-labels",
            github_repo_id=1, installation_id=99,
        ))
    client = TestClient(app)
    item = client.get("/v1/runs", headers=AUTH).json()["items"][0]
    assert item["verdict_id"] == vid
    assert item["repo"] == "o/r"
    assert item["installation_id"] == 99
    assert item["github_repo_id"] == 1
    assert item["pr_number"] == 7
    assert item["title"] == "Add cache"
    assert item["url"] == "https://github.com/o/r/pull/7"
    assert item["tier"] == "reader"
    assert item["source"] == "app"
    assert item["score"] == VERDICT.score
    assert item["band"] == VERDICT.band.value
    assert item["threshold"] == VERDICT.threshold
    assert item["changed_files"] == 12
    assert item["coverage"] == {
        "diff_chars": 100, "sent_chars": 80, "files_sent": 2,
        "files_unseen": ["b.py"], "file_cut": "a.py",
    }
    # VERDICT's one Reason carries no severity — total counts severity-NULL
    # findings (the brief's own note on RunFindingCounts), so total=1 while
    # the severity buckets stay at zero.
    assert item["finding_counts"] == {"total": 1, "high": 0, "medium": 0, "low": 0}
    assert item["job"]["status"] == "done" and item["job"]["attempts"] == 1
    assert item["outcome_14"] == "clean"


def test_runs_serialises_a_row_with_no_pr_meta(tmp_path, monkeypatch):
    """Null pr_meta is a real ledger state, not just a test artifact:
    verdicts.pr_meta is a nullable JSON column (store.py) and save_review's
    `pr_meta` kwarg defaults to None. _with_url assumes pr_meta is a dict —
    every /v1/queue row is filtered on that before it gets there — but
    run_history carries every verdict, including rows saved without one, so
    a bare _with_url(row) call would raise validating None into PRMetadata
    instead of degrading. _run_item falls back for a missing pr_meta by
    synthesizing a title and URL from repo/pr_number, and leaving
    changed_files None rather than invented — a row with no metadata
    genuinely has no denominator."""
    _db(tmp_path, monkeypatch)
    store.save_review(
        "o/r", 9, "deterministic", VERDICT,
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    client = TestClient(app)
    item = client.get("/v1/runs", headers=AUTH).json()["items"][0]
    assert item["title"] == "PR #9"
    assert item["url"] == "https://github.com/o/r/pull/9"
    assert item["changed_files"] is None


# /v1/health — the strip's only data source. Same _db/AUTH shape as /v1/runs.


def test_health_refuses_without_the_operator_token(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    assert TestClient(app).get("/v1/health").status_code == 401


def test_health_404s_a_tenant_key(tmp_path, monkeypatch):
    """Health crosses every installation by design, which is exactly what no
    tenant credential may ever do."""
    _db(tmp_path, monkeypatch)
    monkeypatch.setattr(tenancy, "resolve", lambda t: tenancy.TokenContext(
        installation_id=99, token_id=1, repo_ids=None, scopes=("queue:read",),
    ))
    res = TestClient(app).get("/v1/health", headers={"X-Doug-Token": "dg_tenant"})
    assert res.status_code == 404


def test_health_503s_without_a_ledger(tmp_path, monkeypatch):
    """503, never a zeroed payload. Zeros would render as 'nothing is wrong'
    on a deployment that cannot answer the question at all."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DOUG_API_TOKEN", "t0ken")
    assert TestClient(app).get("/v1/health", headers=AUTH).status_code == 503


def test_health_reports_both_lanes_constants(tmp_path, monkeypatch):
    """The console must never hardcode 900, 7200, 3 or 10."""
    _db(tmp_path, monkeypatch)
    body = TestClient(app).get("/v1/health", headers=AUTH).json()
    assert body["review"]["stall_lease_seconds"] == ingest.STALL_LEASE_SECONDS
    assert body["review"]["max_attempts"] == ingest.MAX_ATTEMPTS
    assert body["outcome"]["stall_lease_seconds"] == outcome_queue.STALL_LEASE_SECONDS
    assert body["outcome"]["max_attempts"] == outcome_queue.MAX_ATTEMPTS


def test_health_carries_the_server_clock_as_of(tmp_path, monkeypatch):
    """Every age the console renders is as_of minus a timestamp. Without it
    the UI would subtract a server-written timestamp from a browser clock,
    which is the timestamp defect Phase 1 already paid for, with an alarm
    attached."""
    _db(tmp_path, monkeypatch)
    body = TestClient(app).get("/v1/health", headers=AUTH).json()
    assert body["as_of"] is not None


# /v1/jobs — the failure list. Same gate and envelope as /v1/runs.


def test_jobs_refuses_without_the_operator_token(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    assert TestClient(app).get("/v1/jobs?lane=review").status_code == 401


def test_jobs_rejects_a_derived_state_as_a_status(tmp_path, monkeypatch):
    """'stalled' and 'retrying' are derived from started_at and attempts,
    not stored. Accepting them here would put the derivation somewhere the
    strip cannot see, and the two surfaces would drift."""
    _db(tmp_path, monkeypatch)
    client = TestClient(app)
    assert client.get("/v1/jobs?lane=review&status=stalled", headers=AUTH).status_code == 422
    assert client.get("/v1/jobs?lane=review&status=retrying", headers=AUTH).status_code == 422
    assert client.get("/v1/jobs?lane=outcome&status=overdue", headers=AUTH).status_code == 422


def test_jobs_accepts_a_stored_status(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    res = TestClient(app).get("/v1/jobs?lane=review&status=failed", headers=AUTH)
    assert res.status_code == 200


def test_jobs_rejects_an_unknown_lane(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    assert TestClient(app).get("/v1/jobs?lane=nope", headers=AUTH).status_code == 422


def test_jobs_rejects_an_out_of_range_limit(tmp_path, monkeypatch):
    """Same 1..500 bound as /v1/runs, so the console's atCap logic carries
    over unchanged."""
    _db(tmp_path, monkeypatch)
    client = TestClient(app)
    assert client.get("/v1/jobs?lane=review&limit=0", headers=AUTH).status_code == 422
    assert client.get("/v1/jobs?lane=review&limit=501", headers=AUTH).status_code == 422


def test_jobs_round_trips_limit_and_offset(tmp_path, monkeypatch):
    """The only way a caller can tell 'this IS every unhealthy job' from
    'this is the first page of more'."""
    _db(tmp_path, monkeypatch)
    body = TestClient(app).get("/v1/jobs?lane=review&limit=7", headers=AUTH).json()
    assert body["limit"] == 7
    assert body["offset"] == 0


def test_jobs_503s_without_a_ledger(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DOUG_API_TOKEN", "t0ken")
    assert TestClient(app).get("/v1/jobs?lane=review", headers=AUTH).status_code == 503


def test_jobs_does_not_leak_undocumented_columns(tmp_path, monkeypatch):
    """select(t) on outcome_jobs returns base_ref, claim_generation and
    created_at too, and JobItem does not declare them. Pydantic v2's default
    extra='ignore' silently drops them today, which is the behaviour we
    want — but nothing pinned it, so a future model_config change could
    start leaking ledger columns into an API response without any test
    noticing. Assert the response carries exactly JobItem's declared
    fields."""
    _db(tmp_path, monkeypatch)
    now = datetime.now(UTC)
    store.enqueue_outcome_jobs(
        99, 4242, 7, "c" * 40, now - timedelta(days=20), "main", window_days=(14,)
    )
    body = TestClient(app).get("/v1/jobs?lane=outcome", headers=AUTH).json()
    assert len(body["items"]) == 1
    assert set(body["items"][0].keys()) == set(JobItem.model_fields)


def test_jobs_rejects_done_under_the_default_unhealthy_view_on_review(
    tmp_path, monkeypatch
):
    """A done review job can never be unhealthy, so status=done composed
    with the default view=unhealthy is empty by construction. 422 names the
    fix rather than returning a list indistinguishable from 'there are
    none'."""
    _db(tmp_path, monkeypatch)
    res = TestClient(app).get("/v1/jobs?lane=review&status=done", headers=AUTH)
    assert res.status_code == 422
    assert "view=all" in res.json()["detail"]


def test_jobs_rejects_superseded_under_the_default_unhealthy_view(
    tmp_path, monkeypatch
):
    """Same reason as done: a superseded job means nothing went wrong."""
    _db(tmp_path, monkeypatch)
    res = TestClient(app).get("/v1/jobs?lane=review&status=superseded", headers=AUTH)
    assert res.status_code == 422
    assert "view=all" in res.json()["detail"]


def test_jobs_rejects_done_under_the_default_unhealthy_view_on_outcome(
    tmp_path, monkeypatch
):
    _db(tmp_path, monkeypatch)
    res = TestClient(app).get("/v1/jobs?lane=outcome&status=done", headers=AUTH)
    assert res.status_code == 422
    assert "view=all" in res.json()["detail"]


def test_jobs_accepts_running_status_under_the_unhealthy_view(tmp_path, monkeypatch):
    """status=running with view=unhealthy means 'running AND stalled' — a
    real, non-empty composition — and must not be caught by the
    never-unhealthy rejection."""
    _db(tmp_path, monkeypatch)
    res = TestClient(app).get(
        "/v1/jobs?lane=review&status=running&view=unhealthy", headers=AUTH
    )
    assert res.status_code == 200


def test_jobs_accepts_pending_status_under_the_unhealthy_view(tmp_path, monkeypatch):
    """status=pending with view=unhealthy is the other composition the
    amendment names as legitimate — a fresh, unattempted job is still
    'unhealthy' by store.job_rows' definition. Must not be caught by the
    never-unhealthy rejection, which names only done/superseded."""
    _db(tmp_path, monkeypatch)
    res = TestClient(app).get(
        "/v1/jobs?lane=review&status=pending&view=unhealthy", headers=AUTH
    )
    assert res.status_code == 200


# /v1/runs/{verdict_id} — the console's forensic endpoint. RV is the same
# reader output test_store.py's find_verdict_by_id tests build: its one
# finding's description matches VERDICT's own reason label, so save_review
# attaches file/severity to it the same way a real reader row would.
RV = api.reader.ReaderVerdict.model_validate(
    {
        "risk_score": 62,
        "rationale": "Unlocked cache write.",
        "findings": [
            {
                "category_slug": "race-condition",
                "description": "Cache write is not guarded",
                "file": "cache.py",
                "severity": "high",
            }
        ],
    }
)


def client_get_detail(verdict_id: int) -> dict:
    res = TestClient(app).get(f"/v1/runs/{verdict_id}", headers=AUTH)
    assert res.status_code == 200, res.text
    return res.json()


def _parsed_utc(iso: str) -> datetime:
    """A response-JSON timestamp, normalised like `_utc` above but for a
    string: sqlite hands DateTime(timezone=True) columns back naive, so
    pydantic serialises them with no offset. The stored instant is UTC
    either way."""
    dt = datetime.fromisoformat(iso)
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def test_run_detail_404s_an_unknown_verdict(tmp_path, monkeypatch):
    """FastAPI's own missing-route 404 is indistinguishable from this one by
    status code alone — the body pins it to the route's not-found branch
    rather than a route that does not exist."""
    _db(tmp_path, monkeypatch)
    client = TestClient(app)
    res = client.get("/v1/runs/4242", headers=AUTH)
    assert res.status_code == 404
    assert res.json()["detail"] == "not found"


def test_run_detail_refuses_without_the_operator_token(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    client = TestClient(app)
    assert client.get("/v1/runs/1").status_code == 401


def test_run_detail_404s_a_tenant_key(tmp_path, monkeypatch):
    """A resolving tenant key is a real credential at the wrong door, so it
    gets the gate's 404 — distinct from the route's own 404 for an unknown
    id above. The row exists here, so only the gate can be producing this:
    if _operator_only ran after the store lookup (or not at all), a
    resolving token would see the row and this would 200."""
    _db(tmp_path, monkeypatch)
    vid = store.save_review(
        "o/r", 7, "reader", VERDICT,
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    monkeypatch.setattr(tenancy, "resolve", lambda t: tenancy.TokenContext(
        installation_id=99, token_id=1, repo_ids=None, scopes=("queue:read",),
    ))
    client = TestClient(app)
    res = client.get(f"/v1/runs/{vid}", headers={"X-Doug-Token": "dg_tenant"})
    assert res.status_code == 404


def test_run_detail_503s_without_a_ledger(tmp_path, monkeypatch):
    """Mirrors test_runs_503s_without_a_ledger for the same route family:
    an operator token that checks out fine (DOUG_API_TOKEN is set and
    matches) still refuses when there is nothing to query."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DOUG_API_TOKEN", "t0ken")
    client = TestClient(app)
    assert client.get("/v1/runs/1", headers=AUTH).status_code == 503


def test_run_detail_reports_a_null_prompt_hash_as_unstamped(tmp_path, monkeypatch):
    """Historical App-path reader verdicts carry NULL because the worker
    never stamped it (the CI endpoint did, masking the bug). Serialising
    that as a match would assert the frozen prompt ran when nobody knows."""
    _db(tmp_path, monkeypatch)
    vid = store.save_review(
        "o/r", 7, "reader", VERDICT, reader_verdict=RV, model="claude-opus-5",
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    body = client_get_detail(vid)
    assert body["prompt_hash"] is None


def test_run_detail_returns_findings_deviations_and_coverage(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    vid = store.save_review(
        "o/r", 7, "reader", VERDICT, reader_verdict=RV, model="claude-opus-5",
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
        coverage=store.Coverage(
            diff_chars=108200, sent_chars=18400, files_sent=4,
            files_unseen=["api/doug/tenancy.py"], file_cut="api/doug/api.py",
        ),
    )
    body = client_get_detail(vid)
    assert body["coverage"]["files_unseen"] == ["api/doug/tenancy.py"]
    assert body["coverage"]["file_cut"] == "api/doug/api.py"
    assert body["reasons"][0]["rule"] == "reader:race-condition"
    assert body["deviations"] == []


def test_run_detail_reports_no_job_as_null_and_no_outcomes_as_empty(tmp_path, monkeypatch):
    """A ledger row can predate any review_jobs claim — job is None, never
    {} — and can have no recorded outcome yet — outcomes/outcome_jobs are
    [], never missing. store.run_detail's docstring names both states."""
    _db(tmp_path, monkeypatch)
    vid = store.save_review(
        "o/r", 7, "reader", VERDICT, reader_verdict=RV, model="claude-opus-5",
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    body = client_get_detail(vid)
    assert body["job"] is None
    assert body["outcomes"] == []
    assert body["outcome_jobs"] == []


def test_run_detail_serialises_a_row_with_no_pr_meta(tmp_path, monkeypatch):
    """pr_meta is a nullable column and save_review defaults it to None —
    every row in the tests above carries it. _with_url assumes pr_meta is a
    dict (the /v1/queue and /v1/runs precedent both filter or guard on that
    before calling it); a bare call on a null one raises validating None
    into PRMetadata, the same crash Task 3 hit and fixed in _run_item.
    `pr` is nulled here rather than synthesized the way _run_item
    synthesizes a title/url: PRMetadata.author has no default, and this
    ledger row does not know one — inventing it would be exactly the
    guessed fact the codebase's None-means-unknown convention refuses to
    write (PRMetadata's own docstring comments: 'never guessed')."""
    _db(tmp_path, monkeypatch)
    vid = store.save_review(
        "o/r", 9, "deterministic", VERDICT,
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    body = client_get_detail(vid)
    assert body["pr"] is None


def test_run_detail_serialises_every_key_of_the_response_contract(tmp_path, monkeypatch):
    """The brief's tests above never touch verdict_id/repo/pr_number/
    installation_id/github_repo_id/pr/scored_at/tier/model/source/head_sha/
    risk_score/rationale/score/band/threshold/intent_alignment/intent_refs/
    job/outcomes/outcome_jobs — a dropped or misspelled key among them would
    pass every test above anyway. This is the contract the console's
    forensics page reads, so one row carries a real pr_meta, a deviation, a
    review job and both outcome tables, and every key is pinned."""
    _db(tmp_path, monkeypatch)
    pr_meta = {
        "number": 7, "title": "Add cache", "author": "dev", "files": ["cache.py"],
        "url": "https://github.com/o/r/pull/7", "changed_files": 3,
    }
    vid = store.save_review(
        "o/r", 7, "reader", VERDICT, reader_verdict=RV, model="claude-opus-5",
        pr_meta=pr_meta,
        coverage=store.Coverage(
            diff_chars=100, sent_chars=80, files_sent=2,
            files_unseen=["b.py"], file_cut="a.py",
        ),
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
        prompt_hash="sha256:abc",
    )
    store.save_deviations(
        vid,
        [api.reader.DeviationFinding(
            type="beyond-ticket", description="Touches billing", severity="medium",
        )],
        intent_refs=["TICKET-1"],
        intent_alignment=70,
    )
    engine = store._get_engine()
    with engine.begin() as conn:
        conn.execute(store.review_jobs.insert().values(
            installation_id=99, github_repo_id=1, repo_full_name="o/r",
            pr_number=7, head_sha="a" * 40, status="done", attempts=1,
            claim_generation=2,
            enqueued_at=datetime(2026, 8, 1, tzinfo=UTC),
            started_at=datetime(2026, 8, 1, 0, 0, 1, tzinfo=UTC),
            finished_at=datetime(2026, 8, 1, 0, 0, 5, tzinfo=UTC),
            verdict_id=vid,
        ))
        conn.execute(store.outcomes.insert().values(
            repo="o/r", pr_number=7, kind="clean", window_days=14,
            observed_at=datetime(2026, 8, 15, tzinfo=UTC), source="git-labels",
            github_repo_id=1, installation_id=99,
        ))
        conn.execute(store.outcome_jobs.insert().values(
            installation_id=99, github_repo_id=1, pr_number=7,
            merge_commit_sha="b" * 40, merged_at=datetime(2026, 8, 1, tzinfo=UTC),
            base_ref="main", window_days=14,
            due_at=datetime(2026, 8, 15, tzinfo=UTC), status="pending",
            created_at=datetime(2026, 8, 1, tzinfo=UTC),
        ))
    body = client_get_detail(vid)
    assert body["verdict_id"] == vid
    assert body["repo"] == "o/r"
    assert body["pr_number"] == 7
    assert body["installation_id"] == 99
    assert body["github_repo_id"] == 1
    assert body["pr"]["title"] == "Add cache"
    assert body["pr"]["url"] == "https://github.com/o/r/pull/7"
    assert body["scored_at"] is not None
    assert body["tier"] == "reader"
    assert body["prompt_hash"] == "sha256:abc"
    assert body["model"] == "claude-opus-5"
    assert body["source"] == "app"
    assert body["head_sha"] == "a" * 40
    assert body["risk_score"] == 62
    assert body["rationale"] == "Unlocked cache write."
    assert body["score"] == VERDICT.score
    assert body["band"] == VERDICT.band.value
    assert body["threshold"] == VERDICT.threshold
    assert body["coverage"] == {
        "diff_chars": 100, "sent_chars": 80, "files_sent": 2,
        "files_unseen": ["b.py"], "file_cut": "a.py",
    }
    assert body["reasons"][0]["rule"] == "reader:race-condition"
    assert body["deviations"] == [
        {"type": "beyond-ticket", "description": "Touches billing", "severity": "medium"},
    ]
    assert body["intent_alignment"] == 70
    assert body["intent_refs"] == ["TICKET-1"]
    assert body["job"]["status"] == "done"
    assert body["job"]["attempts"] == 1
    assert body["job"]["claim_generation"] == 2
    assert body["job"]["error"] is None
    assert body["job"]["enqueued_at"] is not None
    assert body["job"]["started_at"] is not None
    assert body["job"]["finished_at"] is not None
    assert len(body["outcomes"]) == 1
    assert body["outcomes"][0]["kind"] == "clean"
    assert body["outcomes"][0]["window_days"] == 14
    assert body["outcomes"][0]["source"] == "git-labels"
    assert body["outcomes"][0]["detail"] is None
    assert _parsed_utc(body["outcomes"][0]["observed_at"]) == datetime(2026, 8, 15, tzinfo=UTC)
    assert len(body["outcome_jobs"]) == 1
    assert body["outcome_jobs"][0]["window_days"] == 14
    assert body["outcome_jobs"][0]["status"] == "pending"
    assert _parsed_utc(body["outcome_jobs"][0]["due_at"]) == datetime(2026, 8, 15, tzinfo=UTC)
    assert _parsed_utc(body["outcome_jobs"][0]["merged_at"]) == datetime(2026, 8, 1, tzinfo=UTC)


def test_showcase_queue_404s_when_the_repo_is_unset(tmp_path, monkeypatch):
    """Unset means 'this deployment has no showcase', not 'show everything'."""
    _db(tmp_path, monkeypatch)
    monkeypatch.delenv("DOUG_SHOWCASE_REPO", raising=False)
    client = TestClient(app)
    assert client.get("/v1/showcase/queue").status_code == 404


def test_showcase_queue_serves_without_any_token(tmp_path, monkeypatch):
    """The whole point: doug-web must be able to call this holding no
    credential at all."""
    _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_SHOWCASE_REPO", "drewjst/doug")
    client = TestClient(app)
    assert client.get("/v1/showcase/queue").status_code == 200


def test_showcase_queue_does_not_depend_on_the_operator_token(tmp_path, monkeypatch):
    """/v1/queue 503s when DOUG_API_TOKEN is unset (api.py:317-322). If this
    endpoint inherited that, removing the secret from doug-web would take the
    public pages down — the exact failure this endpoint exists to prevent."""
    _db(tmp_path, monkeypatch)
    monkeypatch.delenv("DOUG_API_TOKEN", raising=False)
    monkeypatch.setenv("DOUG_SHOWCASE_REPO", "drewjst/doug")
    client = TestClient(app)
    assert client.get("/v1/showcase/queue").status_code == 200


def test_showcase_queue_ignores_a_caller_supplied_repo(tmp_path, monkeypatch):
    """It is pinned by deployment, never selected by the caller. A ?repo=
    that changed the answer would make a public endpoint a cross-tenant
    selector."""
    _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_SHOWCASE_REPO", "drewjst/doug")
    # A row under the pinned repo, so a ?repo= that actually scoped the
    # query would return a DIFFERENT (empty) result for "someone/private"
    # rather than coincidentally matching an equally-empty ledger.
    store.save_review(
        "drewjst/doug", 1, "reader", VERDICT,
        pr_meta={**PR_META, "number": 1}, installation_id=1, github_repo_id=1,
    )
    client = TestClient(app)
    # Reset immediately before EACH request: the route is backed by a
    # single-slot cache (api._showcase_cache), so a stale reset only
    # before the first request would let the second one — the one
    # carrying the attempted override — serve straight from the cache
    # the first request warmed, never touching the handler's own
    # (non-)handling of `repo` at all.
    monkeypatch.setattr(api, "_showcase_cache", None)
    pinned = client.get("/v1/showcase/queue").json()
    monkeypatch.setattr(api, "_showcase_cache", None)
    attempted = client.get("/v1/showcase/queue?repo=someone/private").json()
    assert pinned == attempted


def test_showcase_queue_serves_only_the_pinned_repos_rows(tmp_path, monkeypatch):
    """Two repos in the ledger, one pinned: the other must not appear."""
    _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_SHOWCASE_REPO", "drewjst/doug")
    # A prior test in this module may have warmed the cache for this
    # response within the last 30s of monotonic time — a cache HIT would
    # never call store.latest_reviews at all and this spy would see
    # nothing. Start from a clean cache so this test's call-count
    # assertion reflects this test's own request, not whatever ran before
    # it.
    monkeypatch.setattr(api, "_showcase_cache", None)
    calls: list[dict] = []
    real = store.latest_reviews

    def spy(**kwargs):
        calls.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(store, "latest_reviews", spy)
    client = TestClient(app)
    assert client.get("/v1/showcase/queue").status_code == 200
    assert calls == [{"repo": "drewjst/doug"}]


def test_showcase_queue_sets_a_public_cache_control_header(tmp_path, monkeypatch):
    """Downstream infrastructure (a CDN, the browser) should be able to
    cache this deliberately-public payload too, not just this process."""
    _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_SHOWCASE_REPO", "drewjst/doug")
    monkeypatch.setattr(api, "_showcase_cache", None)
    client = TestClient(app)
    r = client.get("/v1/showcase/queue")
    assert r.headers["cache-control"] == "public, max-age=30"


def test_showcase_queue_does_not_recompute_within_the_cache_ttl(tmp_path, monkeypatch):
    """store.latest_reviews runs one findings query per row, up to
    limit=200 (store.py:1838) — up to 201 queries per request against a
    scale-to-zero service, with no auth to throttle callers. A short cache
    is the backstop; this proves a second identical request within the TTL
    does not touch the ledger again, and that a request after the TTL
    expires does."""
    _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_SHOWCASE_REPO", "drewjst/doug")
    monkeypatch.setattr(api, "_showcase_cache", None)
    calls: list[dict] = []
    real = store.latest_reviews

    def spy(**kwargs):
        calls.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(store, "latest_reviews", spy)
    now = [1_000.0]
    monkeypatch.setattr(api.time, "monotonic", lambda: now[0])
    client = TestClient(app)

    client.get("/v1/showcase/queue")
    assert len(calls) == 1

    now[0] += 10  # well within the 30s TTL
    client.get("/v1/showcase/queue")
    assert len(calls) == 1  # cache hit — no second query

    now[0] += 30  # TTL now expired
    client.get("/v1/showcase/queue")
    assert len(calls) == 2  # recomputed


def test_showcase_queue_ignores_a_caller_supplied_threshold(tmp_path, monkeypatch):
    """The route takes no caller input, period: `repo` is already ignored
    (test_showcase_queue_ignores_a_caller_supplied_repo above) and
    `threshold` is too. The one real consumer — web/lib/api.ts's
    getQueue() — never sends it and re-bands client-side via
    applyThreshold, so accepting it server-side was pure attack surface: a
    caller-controlled value with no bound, sitting on a public,
    unauthenticated endpoint backed by a process-lifetime cache."""
    _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_SHOWCASE_REPO", "drewjst/doug")
    store.save_review(
        "drewjst/doug", 1, "reader", VERDICT,
        pr_meta={**PR_META, "number": 1}, installation_id=1, github_repo_id=1,
    )
    client = TestClient(app)
    # Reset immediately before EACH request: the route is backed by a
    # single-slot cache (api._showcase_cache), so a stale reset only
    # before the first request would let the second one — the one
    # carrying the attempted override — serve straight from the cache
    # the first request warmed, never touching the handler's own
    # (non-)handling of `threshold` at all.
    monkeypatch.setattr(api, "_showcase_cache", None)
    default = client.get("/v1/showcase/queue").json()
    # 0.99 sits well above the seeded score (0.62) — if threshold were
    # honoured this would flip the row's band and the summary counts.
    monkeypatch.setattr(api, "_showcase_cache", None)
    attempted = client.get("/v1/showcase/queue?threshold=0.99").json()
    assert attempted == default


def test_showcase_queue_cache_cannot_be_grown_by_distinct_threshold_values(
    tmp_path, monkeypatch
):
    """A cache dict keyed on a caller-supplied value would let
    ?threshold=0.0001, 0.0002, ... grow without bound on a public,
    unauthenticated, scale-to-zero service — trading the DB-load
    amplifier this cache exists to fix for a memory-exhaustion one.
    Because the route ignores threshold entirely, every request lands on
    the same single cache slot no matter how many distinct values a
    caller sends."""
    _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_SHOWCASE_REPO", "drewjst/doug")
    monkeypatch.setattr(api, "_showcase_cache", None)
    client = TestClient(app)

    bodies = [
        client.get(f"/v1/showcase/queue?threshold=0.{i:04d}").json()
        for i in range(50)
    ]
    assert all(b == bodies[0] for b in bodies)
    # Not just "same content" — structurally one slot, not a dict a
    # caller-controlled key could have grown to 50 entries.
    assert isinstance(api._showcase_cache, tuple)
    assert len(api._showcase_cache) == 2


# ---------------------------------------------------------------------------
# POST /v1/installations/bind — authority, not visibility.
#
# No test below performs network I/O. The session is a real RS256 JWT minted
# locally against a generated key (session_auth._jwks is monkeypatched, the
# same way tests/test_session_auth.py does it), and every WorkOS call goes
# through workos_client._request, replaced here by a STATEFUL fake: it
# remembers the organizations it created and the memberships it was asked
# for, so idempotency and "nothing was created" are observed facts rather
# than assumptions about a stub.

_BIND_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_BIND_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _BindJWKS:
    """Stands in for jwt.PyJWKClient — only .key is ever read."""

    class _Key:
        def __init__(self, key):
            self.key = key

    def get_signing_key_from_jwt(self, token):
        return self._Key(_BIND_KEY.public_key())


class _FakeWorkOS:
    """Stateful stand-in for workos_client._request.

    `idp_id` is what GET /identities reports for the signed-in user — the
    value the installer check compares. `orgs` maps external_id -> org id and
    starts empty, so the first bind genuinely creates and the second
    genuinely finds.
    """

    def __init__(self, idp_id: str | None = "777", orgs: dict[str, str] | None = None):
        self.idp_id = idp_id
        self.orgs = dict(orgs or {})
        self.memberships: list[tuple[str, str]] = []
        self.calls: list[str] = []

    def __call__(self, method, path, *, json=None):
        self.calls.append(f"{method} {path}")
        if method == "GET" and path.endswith("/identities"):
            if self.idp_id is None:
                return httpx.Response(200, json=[])
            return httpx.Response(
                200, json=[{"idp_id": self.idp_id, "type": "OAuth", "provider": "GithubOAuth"}]
            )
        if method == "GET" and path.startswith("/organizations/external_id/"):
            external_id = path.rsplit("/", 1)[1]
            if external_id in self.orgs:
                return httpx.Response(200, json={"id": self.orgs[external_id]})
            return httpx.Response(404, json={"code": "entity_not_found"})
        if method == "POST" and path == "/organizations":
            external_id = json["external_id"]
            self.orgs.setdefault(external_id, f"org_for_{external_id}")
            return httpx.Response(201, json={"id": self.orgs[external_id]})
        if method == "POST" and path == "/user_management/organization_memberships":
            self.memberships.append((json["user_id"], json["organization_id"]))
            return httpx.Response(201, json={"id": "om_01"})
        raise AssertionError(f"unexpected WorkOS call: {method} {path}")

    def creates(self) -> list[str]:
        return [c for c in self.calls if c.startswith("POST")]


def _bind_env(monkeypatch, idp_id: str | None = "777", orgs=None) -> _FakeWorkOS:
    fake = _FakeWorkOS(idp_id=idp_id, orgs=orgs)
    monkeypatch.setattr(workos_client, "_request", fake)
    monkeypatch.setattr(session_auth, "_jwks", lambda: _BindJWKS())
    monkeypatch.setenv("WORKOS_API_KEY", "sk_test")
    return fake


def _session(key=_BIND_KEY, sub="user_01ABC") -> dict:
    now = int(time.time())
    token = jwt.encode(
        {"iss": "https://auth.workos.com", "sub": sub, "iat": now, "exp": now + 300},
        key,
        algorithm="RS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _installed(installation_id: int, installer: int | None, *, org_id: str | None = None):
    store.upsert_installation(
        installation_id,
        "drewjst",
        "Organization",
        "active",
        installed_by_github_user_id=installer,
    )
    if org_id is not None:
        engine = store._get_engine()
        with engine.begin() as conn:
            conn.execute(
                store.installations.update()
                .where(store.installations.c.installation_id == installation_id)
                .values(workos_org_id=org_id)
            )


def _bound_org(installation_id: int) -> str | None:
    engine = store._get_engine()
    with engine.connect() as conn:
        return conn.execute(
            select(store.installations.c.workos_org_id).where(
                store.installations.c.installation_id == installation_id
            )
        ).scalar_one_or_none()


def _bind(client, installation_id: int, **extra):
    return client.post(
        "/v1/installations/bind",
        json={"installation_id": installation_id, **extra},
        headers=_session(),
    )


_FLOW_SECRET = "install-flow-api-test-secret-32-bytes"


def _flow_token(
    installation_id: int = 1001,
    *,
    sub: str = "user_01ABC",
    nonce: bytes = b"\x01" * 32,
    expires_at: int | None = None,
):
    return install_flow.seal_install_flow(
        nonce=nonce,
        expires_at=expires_at or int(time.time()) + 300,
        subject=sub,
        installation_id=installation_id,
        pkce_retried=False,
        secret=_FLOW_SECRET,
    )


def _tamper_flow_token(token: str) -> str:
    replacement = "A" if token[-1] != "A" else "B"
    tampered = token[:-1] + replacement
    assert tampered != token
    return tampered


def _complete_flow(
    client,
    installation_id: int,
    token: str,
    *,
    sub: str = "user_01ABC",
):
    return client.post(
        "/v1/installations/bind/complete",
        json={"installation_id": installation_id, "flow_token": token},
        headers=_session(sub=sub),
    )


def test_api_tamper_helper_changes_tokens_ending_in_either_candidate_character():
    assert _tamper_flow_token("tokenA") == "tokenB"
    assert _tamper_flow_token("tokenB") == "tokenA"


def test_install_flow_completion_verifies_session_signature_expiry_subject_and_id(
    tmp_path, monkeypatch
):
    """The Setup URL is attacker-callable. A valid WorkOS session and every
    signed flow field must agree before even the installer identity read."""
    _db(tmp_path, monkeypatch)
    _installed(1001, installer=777)
    fake = _bind_env(monkeypatch, idp_id="777")
    monkeypatch.setenv("DOUG_INSTALL_FLOW_SECRET", _FLOW_SECRET)
    client = TestClient(app)
    valid = _flow_token()
    cases = [
        (_tamper_flow_token(valid), "user_01ABC", 1001),
        (_flow_token(expires_at=int(time.time()) - 1), "user_01ABC", 1001),
        (valid, "user_attacker", 1001),
        (valid, "user_01ABC", 1002),
    ]

    for token, sub, installation_id in cases:
        response = _complete_flow(client, installation_id, token, sub=sub)
        assert response.status_code == 404
        assert response.json() == {"detail": "not found"}
    assert fake.calls == []
    assert _bound_org(1001) is None
    assert store.install_flow_consumption(hashlib.sha256(b"\x01" * 32).hexdigest()) is None


def test_install_flow_completion_requires_a_workos_session(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    _installed(1001, installer=777)
    fake = _bind_env(monkeypatch, idp_id="777")
    monkeypatch.setenv("DOUG_INSTALL_FLOW_SECRET", _FLOW_SECRET)

    response = TestClient(app).post(
        "/v1/installations/bind/complete",
        json={"installation_id": 1001, "flow_token": _flow_token()},
    )

    assert response.status_code == 401
    assert fake.calls == []
    assert _bound_org(1001) is None


def test_pre_auth_flow_without_a_bound_subject_cannot_complete(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    _installed(1001, installer=777)
    fake = _bind_env(monkeypatch, idp_id="777")
    monkeypatch.setenv("DOUG_INSTALL_FLOW_SECRET", _FLOW_SECRET)
    token = install_flow.seal_install_flow(
        nonce=b"\x03" * 32,
        expires_at=int(time.time()) + 300,
        subject=None,
        installation_id=1001,
        pkce_retried=False,
        secret=_FLOW_SECRET,
    )

    response = _complete_flow(TestClient(app), 1001, token)

    assert response.status_code == 404
    assert response.json() == {"detail": "not found"}
    assert fake.calls == []
    assert _bound_org(1001) is None


def test_install_flow_completion_reuses_installer_proof_and_non_enumerating_refusal(
    tmp_path, monkeypatch
):
    """A Doug account does not require GitHub. Only repository connection
    does: a session with no linked GitHub identity gets the same refusal as
    any other failed installer-authority proof."""
    _db(tmp_path, monkeypatch)
    _installed(1001, installer=777)
    fake = _bind_env(monkeypatch, idp_id=None)
    monkeypatch.setenv("DOUG_INSTALL_FLOW_SECRET", _FLOW_SECRET)

    response = _complete_flow(TestClient(app), 1001, _flow_token())

    assert response.status_code == 404
    assert response.json() == {"detail": "not found"}
    assert fake.creates() == []
    assert fake.memberships == []
    assert _bound_org(1001) is None


def test_install_flow_completion_binds_and_persists_only_the_nonce_digest(
    tmp_path, monkeypatch, capsys
):
    _db(tmp_path, monkeypatch)
    _installed(1001, installer=777)
    fake = _bind_env(monkeypatch, idp_id="777")
    monkeypatch.setenv("DOUG_INSTALL_FLOW_SECRET", _FLOW_SECRET)
    token = _flow_token()

    response = _complete_flow(TestClient(app), 1001, token)

    assert response.status_code == 204
    assert response.content == b""
    assert _bound_org(1001) == "org_for_gh-inst-1001"
    digest = hashlib.sha256(b"\x01" * 32).hexdigest()
    assert store.install_flow_consumption(digest)["workos_user_id"] == "user_01ABC"
    assert token not in capsys.readouterr().err
    assert fake.memberships == [("user_01ABC", "org_for_gh-inst-1001")]


def test_exact_flow_replay_skips_every_workos_and_authority_side_effect(
    tmp_path, monkeypatch
):
    """A lost 204 may be retried. The durable consumption is the stop sign:
    success is idempotent without another identity read, membership write, or
    installation bind."""
    _db(tmp_path, monkeypatch)
    _installed(1001, installer=777)
    fake = _bind_env(monkeypatch, idp_id="777")
    monkeypatch.setenv("DOUG_INSTALL_FLOW_SECRET", _FLOW_SECRET)
    client = TestClient(app)
    token = _flow_token()
    assert _complete_flow(client, 1001, token).status_code == 204
    fake.calls.clear()

    def no_second_bind(*args, **kwargs):
        raise AssertionError("replay reached the authority write")

    monkeypatch.setattr(store, "consume_install_flow_and_bind", no_second_bind)
    replay = _complete_flow(client, 1001, token)

    assert replay.status_code == 204
    assert fake.calls == []


def test_spent_flow_replayed_for_another_subject_is_refused_before_workos(
    tmp_path, monkeypatch
):
    _db(tmp_path, monkeypatch)
    _installed(1001, installer=777)
    fake = _bind_env(monkeypatch, idp_id="777")
    monkeypatch.setenv("DOUG_INSTALL_FLOW_SECRET", _FLOW_SECRET)
    client = TestClient(app)
    nonce = b"\x02" * 32
    assert _complete_flow(client, 1001, _flow_token(nonce=nonce)).status_code == 204
    fake.calls.clear()

    replay = _complete_flow(
        client,
        1001,
        _flow_token(sub="user_attacker", nonce=nonce),
        sub="user_attacker",
    )

    assert replay.status_code == 404
    assert fake.calls == []


def test_install_flow_completion_parses_untrusted_bodies_without_fastapi_echo(
    tmp_path, monkeypatch
):
    """FastAPI's model errors include rejected input. The flow token is a
    browser-held proof, so every wrong media type/shape/syntax is refused by
    Doug's constant response rather than by a framework-generated 422."""
    _db(tmp_path, monkeypatch)
    _installed(1001, installer=777)
    fake = _bind_env(monkeypatch, idp_id="777")
    monkeypatch.setenv("DOUG_INSTALL_FLOW_SECRET", _FLOW_SECRET)
    marker = "flow-token-marker-that-must-not-echo"
    cases = [
        ("application/json", json.dumps(marker)),
        ("application/json", json.dumps([marker])),
        ("text/plain", marker),
        ("application/x-www-form-urlencoded", f"flow_token={marker}"),
        ("application/json", f'{{"flow_token":"{marker}"'),
        ("application/json", json.dumps({"flow_token": marker})),
    ]

    client = TestClient(app)
    for content_type, content in cases:
        response = client.post(
            "/v1/installations/bind/complete",
            content=content,
            headers={**_session(), "Content-Type": content_type},
        )
        assert response.status_code == 404
        assert response.json() == {"detail": "not found"}
        assert marker not in response.text

    assert fake.calls == []
    assert _bound_org(1001) is None


def test_install_flow_completion_rejects_chunked_body_over_4096_before_json_or_core(
    monkeypatch,
):
    marker = "over-limit-flow-marker-that-must-not-echo"
    payload = json.dumps(
        {"installation_id": 1001, "flow_token": marker + "x" * 4096}
    ).encode()
    assert len(payload) > 4096
    parsed_lengths: list[int] = []
    core_calls = []
    real_loads = api.json.loads

    def recording_loads(value):
        parsed_lengths.append(len(value))
        return real_loads(value)

    def forbidden_core(*args):
        core_calls.append(args)
        return api.Response(status_code=204)

    monkeypatch.setattr(api.json, "loads", recording_loads)
    monkeypatch.setattr(api, "_complete_install_flow_sync", forbidden_core)
    response = TestClient(app).post(
        "/v1/installations/bind/complete",
        content=iter((payload[:2048], payload[2048:])),
        headers={"Authorization": "Bearer marker", "Content-Type": "application/json"},
    )

    assert response.status_code == 404
    # Do not call response.json(): api.json is the stdlib module, so the
    # monkeypatch deliberately observes every json.loads call in this process.
    assert response.text == '{"detail":"not found"}'
    assert marker not in response.text
    assert parsed_lengths == []
    assert core_calls == []


def test_install_flow_completion_parses_exactly_4096_bounded_bytes(monkeypatch):
    token = "bounded-token"
    compact = json.dumps(
        {"installation_id": 1001, "flow_token": token}, separators=(",", ":")
    ).encode()
    payload = compact + b" " * (4096 - len(compact))
    assert len(payload) == 4096
    parsed_lengths: list[int] = []
    core_calls = []
    real_loads = api.json.loads

    def recording_loads(value):
        parsed_lengths.append(len(value))
        return real_loads(value)

    def successful_core(body, authorization):
        core_calls.append((body, authorization))
        return api.Response(status_code=204)

    monkeypatch.setattr(api.json, "loads", recording_loads)
    monkeypatch.setattr(api, "_complete_install_flow_sync", successful_core)
    response = TestClient(app).post(
        "/v1/installations/bind/complete",
        content=payload,
        headers={"Authorization": "Bearer bounded", "Content-Type": "application/json"},
    )

    assert response.status_code == 204
    assert parsed_lengths == [4096]
    assert core_calls == [
        ({"installation_id": 1001, "flow_token": token}, "Bearer bounded")
    ]


def test_install_flow_configuration_fault_is_named_before_workos(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    _installed(1001, installer=777)
    fake = _bind_env(monkeypatch, idp_id="777")
    token = _flow_token()
    client = TestClient(app)

    for configured_secret in (None, "short-secret"):
        if configured_secret is None:
            monkeypatch.delenv("DOUG_INSTALL_FLOW_SECRET", raising=False)
        else:
            monkeypatch.setenv("DOUG_INSTALL_FLOW_SECRET", configured_secret)
        response = _complete_flow(client, 1001, token)
        assert response.status_code == 503
        assert response.json() == {"detail": "install flow not configured"}
        assert token not in response.text

    assert fake.calls == []
    assert _bound_org(1001) is None


def test_install_flow_completion_moves_blocking_authority_work_off_the_event_loop(
    tmp_path, monkeypatch
):
    """The async route must parse its own untrusted bytes, then hand every
    database/WorkOS operation to a worker thread."""
    _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_INSTALL_FLOW_SECRET", _FLOW_SECRET)
    seen: dict[str, str] = {}
    real_read_body = api._read_complete_install_flow_body

    async def marked_read_body(request):
        seen["loop"] = threading.current_thread().name
        return await real_read_body(request)

    def marked_enabled():
        seen["ledger"] = threading.current_thread().name
        return False

    monkeypatch.setattr(api, "_read_complete_install_flow_body", marked_read_body)
    monkeypatch.setattr(store, "enabled", marked_enabled)
    assert inspect.iscoroutinefunction(api.complete_install_flow)

    response = TestClient(app).post(
        "/v1/installations/bind/complete",
        json={"installation_id": 1001, "flow_token": _flow_token()},
        headers=_session(),
    )

    assert response.status_code == 503
    assert seen["loop"] and seen["ledger"]
    assert seen["ledger"] != seen["loop"]


def test_same_nonce_cannot_reach_workos_for_two_installations_concurrently(
    tmp_path, monkeypatch
):
    """The nonce is global authority, not installation-local authority. Two
    signed flows carrying one nonce but different installation ids must be
    serialized before either caller crosses the WorkOS boundary."""
    _db(tmp_path, monkeypatch)
    _installed(1001, installer=777)
    _installed(1002, installer=777)
    fake = _bind_env(monkeypatch, idp_id="777")
    monkeypatch.setenv("DOUG_INSTALL_FLOW_SECRET", _FLOW_SECRET)
    nonce = b"\x09" * 32
    tokens = {1001: _flow_token(1001, nonce=nonce), 1002: _flow_token(1002, nonce=nonce)}
    first_entered = threading.Event()
    second_entered = threading.Event()
    release_first = threading.Event()
    count_lock = threading.Lock()
    identity_calls = 0
    real_request = fake

    def gated_request(method, path, *, json=None):
        nonlocal identity_calls
        if method == "GET" and path.endswith("/identities"):
            with count_lock:
                identity_calls += 1
                call_number = identity_calls
            if call_number == 1:
                first_entered.set()
                assert release_first.wait(5), "coordinator never released first WorkOS call"
            else:
                second_entered.set()
        return real_request(method, path, json=json)

    monkeypatch.setattr(workos_client, "_request", gated_request)
    results: dict[int, int] = {}
    errors: list[BaseException] = []

    def complete(installation_id):
        try:
            results[installation_id] = _complete_flow(
                TestClient(app), installation_id, tokens[installation_id]
            ).status_code
        except BaseException as exc:  # surfaced on the coordinating test thread
            errors.append(exc)

    first = threading.Thread(target=complete, args=(1001,))
    second = threading.Thread(target=complete, args=(1002,))
    first.start()
    assert first_entered.wait(5), "first caller never reached WorkOS"
    second.start()
    second_crossed_before_spend = second_entered.wait(0.5)
    release_first.set()
    first.join(5)
    second.join(5)

    assert not first.is_alive() and not second.is_alive()
    assert errors == []
    assert second_crossed_before_spend is False
    assert results == {1001: 204, 1002: 404}
    assert identity_calls == 1
    assert sum(_bound_org(i) is not None for i in (1001, 1002)) == 1
    consumed = store.install_flow_consumption(hashlib.sha256(nonce).hexdigest())
    assert consumed["installation_id"] == 1001


def test_install_completions_do_not_starve_a_two_connection_main_pool(
    tmp_path, monkeypatch
):
    """Session advisory locks must not occupy the ledger pool while WorkOS
    and binding helpers need that same pool. Two connections is enough for
    two concurrent completions when locking has its own bounded engine."""
    url = _db(tmp_path, monkeypatch)
    main_engine = create_engine(
        url,
        pool_size=2,
        max_overflow=0,
        pool_timeout=0.25,
    )
    store.metadata.create_all(main_engine)
    monkeypatch.setattr(store, "_engine", main_engine)
    monkeypatch.setattr(store, "_engine_url", url)
    _installed(1001, installer=777)
    _installed(1002, installer=777)
    fake = _bind_env(monkeypatch, idp_id="777")
    monkeypatch.setenv("DOUG_INSTALL_FLOW_SECRET", _FLOW_SECRET)
    tokens = {
        1001: _flow_token(1001, nonce=b"\x11" * 32),
        1002: _flow_token(1002, nonce=b"\x12" * 32),
    }
    first_workos_entered = threading.Event()
    release_first = threading.Event()
    request_lock = threading.Lock()
    identity_calls = 0
    real_request = fake

    def gated_request(method, path, *, json=None):
        nonlocal identity_calls
        if method == "GET" and path.endswith("/identities"):
            with request_lock:
                identity_calls += 1
                call_number = identity_calls
            if call_number == 1:
                first_workos_entered.set()
                assert release_first.wait(5), "coordinator never released first flow"
        return real_request(method, path, json=json)

    monkeypatch.setattr(workos_client, "_request", gated_request)
    results: dict[int, int] = {}
    errors: list[BaseException] = []
    finished = {installation_id: threading.Event() for installation_id in tokens}

    def complete(installation_id):
        try:
            results[installation_id] = _complete_flow(
                TestClient(app), installation_id, tokens[installation_id]
            ).status_code
        except BaseException as exc:
            errors.append(exc)
        finally:
            finished[installation_id].set()

    first = threading.Thread(target=complete, args=(1001,))
    second = threading.Thread(target=complete, args=(1002,))
    try:
        first.start()
        assert first_workos_entered.wait(5), "first flow never reached WorkOS"
        second.start()
        second_finished_while_first_held_lock = finished[1002].wait(0.5)
        release_first.set()
        first.join(5)
        second.join(5)

        assert not first.is_alive() and not second.is_alive()
        assert second_finished_while_first_held_lock is False
        assert errors == []
        assert results == {1001: 204, 1002: 204}
        assert _bound_org(1001) == "org_for_gh-inst-1001"
        assert _bound_org(1002) == "org_for_gh-inst-1002"
    finally:
        main_engine.dispose()


def test_bind_refuses_an_installation_the_caller_can_read_but_not_administer(
    tmp_path, monkeypatch
):
    """The exact claimable-tenant attack. GET /user/installations answers on
    :read, so visibility is NOT authority. A caller whose GitHub id does not
    match installed_by_github_user_id must be refused even though the
    installation is genuinely visible to them.

    The first half is not decoration: it proves this caller, this session and
    this ledger DO produce a 204 — so the refusal below can only come from
    the one thing that changed, the recorded installer."""
    _db(tmp_path, monkeypatch)
    _installed(1001, installer=777)  # installed by the signed-in user
    _installed(1002, installer=999)  # someone else's, merely visible
    fake = _bind_env(monkeypatch, idp_id="777")
    client = TestClient(app)

    assert _bind(client, 1001).status_code == 204
    assert _bound_org(1001) == "org_for_gh-inst-1001"

    refused = _bind(client, 1002)
    assert refused.status_code == 404
    assert _bound_org(1002) is None
    assert fake.memberships == [("user_01ABC", "org_for_gh-inst-1001")]


def test_bind_refuses_an_installation_with_no_recorded_installer(tmp_path, monkeypatch):
    """Pre-Task-1 rows carry NULL. NULL must never compare equal to anything —
    a fail-open here would let ANY signed-in user claim every legacy tenant,
    including the operator's own 150424894."""
    _db(tmp_path, monkeypatch)
    _installed(1001, installer=777)
    _installed(150424894, installer=None)  # populated by MT0 webhook redelivery
    fake = _bind_env(monkeypatch, idp_id="777")
    client = TestClient(app)

    assert _bind(client, 1001).status_code == 204
    spent = len(fake.calls)

    refused = _bind(client, 150424894)
    assert refused.status_code == 404
    assert _bound_org(150424894) is None
    # Cheapest-first, same posture as tenancy.verify_org_admin: a row that can
    # never prove authority costs WorkOS nothing at all, not even the identity
    # lookup.
    assert fake.calls[spent:] == []


def test_bind_is_idempotent_for_the_same_org(tmp_path, monkeypatch):
    """installation.created is replayable via GitHub's Redeliver button."""
    _db(tmp_path, monkeypatch)
    _installed(1001, installer=777)
    fake = _bind_env(monkeypatch, idp_id="777")
    client = TestClient(app)

    assert _bind(client, 1001).status_code == 204
    assert _bind(client, 1001).status_code == 204
    assert _bound_org(1001) == "org_for_gh-inst-1001"
    # One organization, not two: the second bind found the first one's.
    assert fake.creates().count("POST /organizations") == 1


def test_bind_refuses_to_move_an_installation_to_a_different_org(tmp_path, monkeypatch):
    """Re-binding a live installation to another organization is a takeover,
    not an update.

    Both installations below are bound already and both callers prove the same
    authority; the ONLY difference is whether the bound org is the one this
    installation's external_id resolves to."""
    _db(tmp_path, monkeypatch)
    _installed(1001, installer=777, org_id="org_manual")
    _installed(1002, installer=777, org_id="org_for_gh-inst-1002")
    _installed(1003, installer=777, org_id="org_ghost")
    fake = _bind_env(
        monkeypatch,
        idp_id="777",
        orgs={"gh-inst-1001": "org_canonical", "gh-inst-1002": "org_for_gh-inst-1002"},
    )
    client = TestClient(app)

    assert _bind(client, 1002).status_code == 204  # already bound to its own org

    refused = _bind(client, 1001)
    assert refused.status_code == 409
    assert _bound_org(1001) == "org_manual"
    assert ("user_01ABC", "org_canonical") not in fake.memberships

    # A row naming an organization its own external_id does not resolve to is
    # inconsistent state, not a bind to complete — and refusing it must leave
    # nothing behind, so no organization is created on the way to the 409.
    assert _bind(client, 1003).status_code == 409
    assert _bound_org(1003) == "org_ghost"
    assert "POST /organizations" not in fake.calls


def test_bind_refuses_a_non_numeric_idp_id_and_says_so(tmp_path, monkeypatch, capsys):
    """idp_id's GitHub format is undocumented and unmeasured. If it is not the
    numeric user id, bind must refuse AND log the value, so the first real
    attempt is diagnosable in one query rather than silently denying."""
    _db(tmp_path, monkeypatch)
    _installed(1001, installer=777)
    fake = _bind_env(monkeypatch, idp_id="github|777")
    client = TestClient(app)

    refused = _bind(client, 1001)
    assert refused.status_code == 404
    assert _bound_org(1001) is None
    assert fake.memberships == []
    err = capsys.readouterr().err
    assert "github|777" in err  # the value received, not just "refused"
    assert "idp_id" in err

    # Same route, same session, same row: only the format of idp_id changed.
    _bind_env(monkeypatch, idp_id="777")
    assert _bind(TestClient(app), 1001).status_code == 204


def test_bind_never_calls_workos_when_the_installer_check_fails(tmp_path, monkeypatch):
    """Authority first, side effects second: a refused caller must not create
    an organization or a membership. Same cheapest-first, spend-nothing-on-a-
    caller-who-proves-nothing posture as tenancy.verify_org_admin.

    The identity lookup itself is a read and is allowed — it is what produces
    the id being checked. What must not happen is a WRITE."""
    _db(tmp_path, monkeypatch)
    _installed(1002, installer=999)
    fake = _bind_env(monkeypatch, idp_id="777")
    client = TestClient(app)

    assert _bind(client, 1002).status_code == 404
    assert fake.creates() == []
    assert fake.memberships == []
    assert fake.calls == ["GET /user_management/users/user_01ABC/identities"]

    # The fake and the route DO reach WorkOS when authority holds — without
    # this, "no POSTs" would pass even if bind were broken end to end.
    _installed(1001, installer=777)
    assert _bind(client, 1001).status_code == 204
    assert fake.creates() == [
        "POST /organizations",
        "POST /user_management/organization_memberships",
    ]


def test_bind_ignores_a_client_supplied_workos_org_id(tmp_path, monkeypatch):
    """The org id never crosses the wire. Accepting one is what made org
    squatting possible — bind a victim's org id first and Task 1's UNIQUE
    index blocks their real bind permanently — so the parameter was removed
    rather than defended against."""
    _db(tmp_path, monkeypatch)
    _installed(1001, installer=777)
    _bind_env(monkeypatch, idp_id="777")
    client = TestClient(app)

    assert _bind(client, 1001, workos_org_id="org_victim").status_code == 204
    assert _bound_org(1001) == "org_for_gh-inst-1001"


def test_bind_refuses_a_forged_session(tmp_path, monkeypatch):
    """Signed with a key JWKS never reported. The endpoint verifies the
    session itself; it does not trust the payload."""
    _db(tmp_path, monkeypatch)
    _installed(1001, installer=777)
    fake = _bind_env(monkeypatch, idp_id="777")
    client = TestClient(app)

    forged = client.post(
        "/v1/installations/bind",
        json={"installation_id": 1001},
        headers=_session(key=_BIND_OTHER_KEY),
    )
    assert forged.status_code == 401
    assert fake.calls == []
    assert _bound_org(1001) is None


def test_bind_refuses_without_a_session(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    _installed(1001, installer=777)
    _bind_env(monkeypatch, idp_id="777")
    res = TestClient(app).post("/v1/installations/bind", json={"installation_id": 1001})
    assert res.status_code == 401


def test_bind_503s_when_session_auth_is_unconfigured(tmp_path, monkeypatch):
    """WORKOS_CLIENT_ID missing is a deployment fault, not a forged token —
    api.py:391's named-503 idiom, so it is diagnosable instead of looking
    like every session being refused."""
    _db(tmp_path, monkeypatch)
    _installed(1001, installer=777)
    # The REAL _jwks runs here — that is the point. Only its configuration is
    # taken away, and the cached client is cleared so a previous test's
    # instance cannot answer for it.
    monkeypatch.setattr(workos_client, "_request", _FakeWorkOS())
    monkeypatch.delenv("WORKOS_CLIENT_ID", raising=False)
    monkeypatch.setattr(session_auth, "_jwks_client", None)
    res = _bind(TestClient(app), 1001)
    assert res.status_code == 503
    assert res.json()["detail"] == "session auth not configured"


def test_bind_503s_when_workos_is_unconfigured(tmp_path, monkeypatch):
    """The API key is the other half of the same deployment promise."""
    _db(tmp_path, monkeypatch)
    _installed(1001, installer=777)
    monkeypatch.setattr(session_auth, "_jwks", lambda: _BindJWKS())
    monkeypatch.delenv("WORKOS_API_KEY", raising=False)

    def _explode(*a, **k):
        raise AssertionError("network reached without an API key")

    monkeypatch.setattr(workos_client, "_send", _explode)
    res = _bind(TestClient(app), 1001)
    assert res.status_code == 503
    assert _bound_org(1001) is None


def test_bind_503s_without_a_ledger(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    _bind_env(monkeypatch, idp_id="777")
    res = TestClient(app).post(
        "/v1/installations/bind", json={"installation_id": 1001}, headers=_session()
    )
    assert res.status_code == 503


def test_bind_503s_when_workos_is_unreachable(tmp_path, monkeypatch):
    """An outage is not a failed identity check. A 404 here would tell a real
    installer their proof was wrong during someone else's incident."""
    _db(tmp_path, monkeypatch)
    _installed(1001, installer=777)
    monkeypatch.setattr(session_auth, "_jwks", lambda: _BindJWKS())
    monkeypatch.setenv("WORKOS_API_KEY", "sk_test")

    def _down(method, url, *, headers, json):
        raise httpx.ConnectError("workos: connection refused")

    # Patched at the transport seam, not at _request: the translation from
    # httpx's exception tree to WorkOSError is the thing under test here.
    monkeypatch.setattr(workos_client, "_send", _down)
    res = _bind(TestClient(app), 1001)
    assert res.status_code == 503
    assert _bound_org(1001) is None


def test_bind_re_proves_the_installer_against_the_row_it_writes(tmp_path, monkeypatch):
    """The row read before the identity hop is a snapshot taken across a
    network call. An uninstall and reinstall by someone else inside that
    window rewrites installed_by_github_user_id, and binding on the stale
    fact would hand this tenant to the previous installer. The proof is
    repeated against the row read under the lock — the same row the write
    lands on."""
    _db(tmp_path, monkeypatch)
    _installed(1001, installer=777)
    _installed(1002, installer=777)
    fake = _bind_env(monkeypatch, idp_id="777")
    client = TestClient(app)

    assert _bind(client, 1001).status_code == 204  # the unraced path still binds

    real = store.installation_bind_row
    reads: list[int] = []

    def _reinstalled_midway(installation_id: int):
        row = real(installation_id)
        reads.append(installation_id)
        if row is not None and reads.count(installation_id) > 1:
            # The reinstall lands between the two reads: same installation,
            # a different person's id on it now.
            return {**row, "installed_by_github_user_id": 999}
        return row

    monkeypatch.setattr(store, "installation_bind_row", _reinstalled_midway)
    refused = _bind(client, 1002)
    assert refused.status_code == 404
    assert _bound_org(1002) is None
    assert ("user_01ABC", "org_for_gh-inst-1002") not in fake.memberships


# ---------------------------------------------------------------------------
# POST /v1/sessions/entitlements — persist the scope, never the credential.
#
# No test below performs network I/O. The session is the same locally minted
# RS256 JWT the bind tests use, and every GitHub call goes through
# entitlements._send — this module's ONE network boundary — replaced here by a
# fake that records the headers it was given, so "the token reached GitHub and
# nothing else" is an observed fact rather than an assumption about a stub.

# Doug's own GitHub App id, as api/deploy/gcp.sh sets it in both services.
_DOUG_APP_ID = "4450932"
# Distinctive on purpose: every "this must not appear" assertion below greps
# for this exact string in a response body, a log, a table dump, and the
# database file itself.
_PROVIDER_TOKEN = "ghu_never_persist_me"


class _FakeGitHubUser:
    """Stands in for entitlements._send. Answers one page of installations and
    one page of repositories per installation, or a status override."""

    def __init__(self, tenants: dict[int, list[int]], status: dict | None = None):
        self.tenants = tenants
        self.status = status or {}
        self.headers: list[dict] = []
        self.paths: list[str] = []

    def __call__(self, url, *, headers, params):
        path = url[len(entitlements.GITHUB_API) :]
        self.paths.append(path)
        self.headers.append(headers)
        if path in self.status:
            return httpx.Response(self.status[path], json={"message": "no"})
        if path == "/user/installations":
            return httpx.Response(
                200,
                json={
                    "installations": [
                        {"id": i, "app_id": int(_DOUG_APP_ID), "repository_selection": "selected"}
                        for i in self.tenants
                    ]
                },
            )
        installation_id = int(path.split("/")[3])
        return httpx.Response(
            200,
            json={
                "repositories": [
                    {"id": r, "full_name": f"drewjst/repo{r}"}
                    for r in self.tenants[installation_id]
                ]
            },
        )


def _entitlement_env(monkeypatch, tenants=None, status=None) -> _FakeGitHubUser:
    fake = _FakeGitHubUser({1001: [11, 12]} if tenants is None else tenants, status)
    monkeypatch.setattr(entitlements, "_send", fake)
    monkeypatch.setattr(session_auth, "_jwks", lambda: _BindJWKS())
    monkeypatch.setenv("DOUG_GITHUB_APP_ID", _DOUG_APP_ID)
    return fake


def _record(client, **body):
    return client.post(
        "/v1/sessions/entitlements",
        json={"provider": "GithubOAuth", "token": _PROVIDER_TOKEN, **body},
        headers=_session(),
    )


def _scope(workos_user_id: str) -> list[tuple[int, frozenset]]:
    return [
        (row["installation_id"], row["repo_ids"])
        for row in store.session_entitlements_for(workos_user_id)
    ]


def _entitlement_rows_text() -> str:
    """Every column of every row, as text — so "the token is not stored" is
    asserted against the whole table, not against the columns a reader
    remembered to check."""
    with store._get_engine().connect() as conn:
        return "\n".join(str(tuple(r)) for r in conn.execute(select(store.session_entitlements)))


def test_entitlements_are_written_for_the_jwt_subject_not_a_body_supplied_user(
    tmp_path, monkeypatch
):
    """The security test. A body-supplied user id would let any signed-in
    caller write another user's scope — and since a scope is what a later
    read is checked against, writing someone else's is writing yourself into
    their tenant.

    The caller below names a victim in every field a body could plausibly use.
    The first assertion is not decoration: it proves this caller, this session
    and this ledger DO produce a real row, so the victim's empty scope can
    only come from where the key was read.
    """
    _db(tmp_path, monkeypatch)
    _entitlement_env(monkeypatch)
    client = TestClient(app)

    res = _record(
        client,
        workos_user_id="user_VICTIM",
        user_id="user_VICTIM",
        sub="user_VICTIM",
        installation_id=1001,
    )
    assert res.status_code == 204
    assert _scope("user_01ABC") == [(1001, frozenset({11, 12}))]
    assert _scope("user_VICTIM") == []


def test_the_provider_token_is_never_stored_logged_or_returned(tmp_path, monkeypatch, capsys):
    """No credential at rest. The token arrives, does its one job, and is
    gone — the row that outlives it is the conclusion it proved.

    Checked in all four places it could survive: the response body, the
    stored row, stderr, and the database file itself (bytes, so a token
    written to some OTHER table would be caught too).
    """
    _db(tmp_path, monkeypatch)
    fake = _entitlement_env(monkeypatch)
    client = TestClient(app)

    res = _record(client)
    assert res.status_code == 204

    # It genuinely travelled to GitHub, and the derivation genuinely landed —
    # without both, "absent everywhere" would pass on an endpoint that never
    # used the token at all.
    assert fake.headers[0]["Authorization"] == f"Bearer {_PROVIDER_TOKEN}"
    assert _scope("user_01ABC") == [(1001, frozenset({11, 12}))]

    assert _PROVIDER_TOKEN not in res.text
    assert _PROVIDER_TOKEN not in str(res.headers), "a header is a response too"
    assert _PROVIDER_TOKEN not in _entitlement_rows_text()
    assert _PROVIDER_TOKEN.encode() not in (tmp_path / "doug.db").read_bytes()
    err = capsys.readouterr().err
    assert "user_01ABC" in err, "the derivation is logged at all"
    assert _PROVIDER_TOKEN not in err


def test_a_first_time_user_with_no_organization_can_record_entitlements(tmp_path, monkeypatch):
    """A stranger's first sign-in has no org_id — that claim appears only once
    an organization is selected. Authenticating with resolve_session here
    would be circular: it fails closed without org_id, so the endpoint that
    exists to give a new user their scope could never be reached by one."""
    _db(tmp_path, monkeypatch)
    _entitlement_env(monkeypatch)
    client = TestClient(app)

    assert _record(client).status_code == 204
    assert _scope("user_01ABC") == [(1001, frozenset({11, 12}))]

    # The same session, through the stricter resolver, is refused — which is
    # what makes the 204 above evidence about WHICH check the route runs.
    assert (
        session_auth.resolve_session(_session()["Authorization"], frozenset({11})) is None
    )


def test_entitlements_refuse_a_forged_session(tmp_path, monkeypatch):
    """Signed with a key JWKS never reported. Nothing is derived and nothing
    is written — a forged session must not even spend a GitHub call."""
    _db(tmp_path, monkeypatch)
    fake = _entitlement_env(monkeypatch)
    client = TestClient(app)

    forged = client.post(
        "/v1/sessions/entitlements",
        json={"provider": "GithubOAuth", "token": _PROVIDER_TOKEN},
        headers=_session(key=_BIND_OTHER_KEY),
    )
    assert forged.status_code == 401
    assert fake.paths == []
    assert _scope("user_01ABC") == []

    # The same route, the same body, a real session: 204. Without this the
    # assertions above would pass on a route that refused everyone.
    assert _record(client).status_code == 204


def test_entitlements_refuse_without_a_session(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    _entitlement_env(monkeypatch)
    res = TestClient(app).post(
        "/v1/sessions/entitlements", json={"provider": "github", "token": _PROVIDER_TOKEN}
    )
    assert res.status_code == 401


def test_entitlements_503_when_session_auth_is_unconfigured(tmp_path, monkeypatch):
    """WORKOS_CLIENT_ID missing is a deployment fault, not a forged token —
    api.py:391's named-503 idiom, same as bind's."""
    _db(tmp_path, monkeypatch)
    # The REAL _jwks runs here — that is the point, so _entitlement_env's
    # stub is deliberately not used. Only its configuration is taken away,
    # and the cached client is cleared so a previous test's instance cannot
    # answer for it. It raises before any network call.
    monkeypatch.setattr(entitlements, "_send", _FakeGitHubUser({1001: [11, 12]}))
    monkeypatch.setenv("DOUG_GITHUB_APP_ID", _DOUG_APP_ID)
    monkeypatch.delenv("WORKOS_CLIENT_ID", raising=False)
    monkeypatch.setattr(session_auth, "_jwks_client", None)

    res = _record(TestClient(app))
    assert res.status_code == 503
    assert res.json()["detail"] == "session auth not configured"


def test_entitlements_503_without_a_ledger(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    _entitlement_env(monkeypatch)
    assert _record(TestClient(app)).status_code == 503


def test_entitlements_503_when_the_github_app_id_is_missing(tmp_path, monkeypatch):
    """Without it, Doug cannot tell its own installations from every other
    app's in the caller's list. Storing an empty scope instead would look
    exactly like "you have no tenants" and never recover."""
    _db(tmp_path, monkeypatch)
    _entitlement_env(monkeypatch)
    monkeypatch.delenv("DOUG_GITHUB_APP_ID", raising=False)

    res = _record(TestClient(app))
    assert res.status_code == 503
    assert res.json()["detail"] == "github app not configured"
    assert _scope("user_01ABC") == []


def test_a_rejected_provider_token_401s_and_leaves_the_stored_scope_alone(tmp_path, monkeypatch):
    """An expired token is the caller's to fix, so it is a 401 and not a 503.
    What it must NEVER be is an empty derivation: that answer gets stored, and
    storing it would erase a live tenant's scope on the strength of a stale
    credential."""
    _db(tmp_path, monkeypatch)
    _entitlement_env(monkeypatch)
    client = TestClient(app)
    assert _record(client).status_code == 204

    _entitlement_env(monkeypatch, status={"/user/installations": 401})
    assert _record(client).status_code == 401
    assert _scope("user_01ABC") == [(1001, frozenset({11, 12}))]


def test_a_provider_outage_503s_and_leaves_the_stored_scope_alone(tmp_path, monkeypatch):
    """Same rule from the other side: GitHub being down is not proof that
    this user is entitled to nothing."""
    _db(tmp_path, monkeypatch)
    _entitlement_env(monkeypatch)
    client = TestClient(app)
    assert _record(client).status_code == 204

    def _down(url, *, headers, params):
        raise httpx.ConnectError("github: connection refused")

    monkeypatch.setattr(entitlements, "_send", _down)
    assert _record(client).status_code == 503
    assert _scope("user_01ABC") == [(1001, frozenset({11, 12}))]


def test_a_body_missing_the_provider_is_refused_without_echoing_the_token(tmp_path, monkeypatch):
    """MEASURED (2026-08-10), not assumed: FastAPI's validation error carries
    the offending input, and for a MISSING field pydantic reports the WHOLE
    BODY as that input — so a required `provider` would echo the token
    straight back to the caller in a 422. Defaults on both fields make that
    error unreachable; the handler refuses the empty pair itself."""
    _db(tmp_path, monkeypatch)
    _entitlement_env(monkeypatch)
    client = TestClient(app)

    res = client.post(
        "/v1/sessions/entitlements",
        json={"token": _PROVIDER_TOKEN},
        headers=_session(),
    )
    assert res.status_code == 400
    assert _PROVIDER_TOKEN not in res.text
    assert _scope("user_01ABC") == []

    # A body with a provider and no token is the same refusal, and the full
    # pair still works — so the 400 is about what is missing, not about the
    # route being broken.
    assert client.post(
        "/v1/sessions/entitlements", json={"provider": "github"}, headers=_session()
    ).status_code == 400
    assert _record(client).status_code == 204


def test_an_unknown_provider_records_no_tenants_rather_than_failing(tmp_path, monkeypatch):
    """Reachable the moment a second WorkOS connection exists. Someone who
    signed in without GitHub sees nothing, and gets a 204 rather than a 500 —
    they signed in successfully, they simply have no tenants."""
    _db(tmp_path, monkeypatch)
    fake = _entitlement_env(monkeypatch)
    client = TestClient(app)

    assert _record(client, provider="GoogleOAuth").status_code == 204
    assert _scope("user_01ABC") == []
    assert fake.paths == [], "an unknown provider must not spend a GitHub call"
