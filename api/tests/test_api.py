import hashlib
import hmac
import json
import threading
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from doug import api, app_auth, ingest, store, worker
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
    job_id = ingest.enqueue(150424894, 987, "drewjst/doug", 7, "a" * 40)
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
        base=SimpleNamespace(repo=SimpleNamespace(id=987, full_name="drewjst/doug")),
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


def _pr_payload(action="opened", *, draft=False, head_repo_id=987, sha="a" * 40, number=7):
    head_repo = None if head_repo_id is None else {"id": head_repo_id}
    return {
        "action": action,
        "installation": INSTALLATION,
        "pull_request": {
            "number": number,
            "draft": draft,
            "head": {"sha": sha, "repo": head_repo},
            "base": {"repo": {"id": 987, "full_name": "drewjst/doug"}},
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
    assert j["status"] == "pending"
    assert kicks == ["drain"]


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
):
    """A `closed` delivery. `merged` varies independently of the other two
    fields on purpose — see test_a_closed_but_unmerged_pull_request_writes_nothing.
    """
    return {
        "action": "closed",
        "installation": INSTALLATION,
        "pull_request": {
            "number": number,
            "draft": False,
            "merged": merged,
            "merged_at": merged_at,
            "merge_commit_sha": merge_sha,
            "head": {"sha": "a" * 40, "repo": {"id": 987}},
            "base": {"ref": base_ref, "repo": {"id": base_repo_id, "full_name": "drewjst/doug"}},
        },
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

    (job,) = _table(tmp_path, store.outcome_jobs)
    assert job["installation_id"] == 150424894
    assert job["github_repo_id"] == 987
    assert job["pr_number"] == 7
    assert job["merge_commit_sha"] == "c" * 40
    assert job["base_ref"] == "main"
    assert job["window_days"] == 14
    assert job["status"] == "pending"
    # No read bought, and nothing queued that would buy one.
    assert _table(tmp_path, store.review_jobs) == []
    assert kicks == []


def test_the_outcome_window_is_measured_from_the_merge_not_from_now(tmp_path, monkeypatch):
    """due_at is merged_at + 14 days, computed from the payload's own
    timestamp. Deriving it from the wall clock would silently re-date every
    row a redelivery or a backfill ever touched, and the window is what the
    published defect-rate denominator means."""
    _hook_env(tmp_path, monkeypatch)
    _webhook("pull_request", _closed_payload())

    (job,) = _table(tmp_path, store.outcome_jobs)
    assert _utc(job["merged_at"]) == datetime(2020, 3, 1, 12, 0, tzinfo=UTC)
    assert _utc(job["due_at"]) == datetime(2020, 3, 15, 12, 0, tzinfo=UTC)


def test_a_redelivered_merge_does_not_start_a_second_clock(tmp_path, monkeypatch):
    """GitHub redelivers on its own schedule. Two 'closed' deliveries for one
    merge must be one observation window, not two — a second row would be a
    second vote in the denominator for a single merge."""
    _hook_env(tmp_path, monkeypatch)
    assert _webhook("pull_request", _closed_payload()).status_code == 202
    assert _webhook("pull_request", _closed_payload()).status_code == 202
    assert len(_table(tmp_path, store.outcome_jobs)) == 1


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


def _comparison_db(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/comparison.db")
    monkeypatch.setenv("DOUG_API_TOKEN", "secret")
    assert store.enabled()


def _comparison_api_review(
    *, app: bool, legacy_ci: bool = False, coverage=None, pr_meta=None
) -> int:
    sha = "a" * 40
    verdict = api.Verdict(
        score=0.2,
        band=api.Band.CLEARED,
        threshold=0.3,
        reasons=[],
    )
    identity = (
        {"installation_id": 10, "github_repo_id": 20, "head_sha": sha, "source": "app"}
        if app
        else {} if legacy_ci else {"head_sha": sha}
    )
    verdict_id = store.save_review(
        "o/r",
        33,
        "reader",
        verdict,
        pr_meta=(
            {"number": 33, "title": "Compare paths", "author": "dev", "files": [],
             "head_sha": sha}
            if pr_meta is None else pr_meta
        ),
        coverage=coverage,
        **identity,
    )
    assert verdict_id is not None
    return verdict_id


def test_comparisons_requires_the_shared_token(monkeypatch):
    monkeypatch.setenv("DOUG_API_TOKEN", "secret")
    assert client.get("/v1/comparisons").status_code == 401


def test_comparisons_refuses_when_the_token_is_unconfigured(monkeypatch):
    monkeypatch.delenv("DOUG_API_TOKEN", raising=False)
    response = client.get(
        "/v1/comparisons", headers={"X-Doug-Token": "anything"}
    )
    assert response.status_code == 503


def test_comparisons_refuses_when_the_ledger_is_unconfigured(monkeypatch):
    monkeypatch.setenv("DOUG_API_TOKEN", "secret")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    response = client.get(
        "/v1/comparisons", headers={"X-Doug-Token": "secret"}
    )
    assert response.status_code == 503


def test_comparisons_rejects_a_limit_outside_one_through_two_hundred(
    tmp_path, monkeypatch
):
    _comparison_db(tmp_path, monkeypatch)
    for limit in (0, 201):
        response = client.get(
            "/v1/comparisons",
            params={"limit": limit},
            headers={"X-Doug-Token": "secret"},
        )
        assert response.status_code == 422


def test_comparisons_serializes_both_paths_duplicates_and_coverage(
    tmp_path, monkeypatch
):
    _comparison_db(tmp_path, monkeypatch)
    coverage = api.reader.Coverage(
        diff_chars=20,
        sent_chars=10,
        files_sent=1,
        files_unseen=["second.py"],
        file_cut="first.py",
    )
    app_one = _comparison_api_review(app=True, coverage=coverage)
    app_two = _comparison_api_review(app=True)
    current_ci = _comparison_api_review(
        app=False,
        pr_meta={"number": 33, "title": "Current CI", "author": "dev", "files": []},
    )
    legacy_ci = _comparison_api_review(app=False, legacy_ci=True)
    one_app_id = store.save_review(
        "o/r",
        33,
        "reader",
        api.Verdict(score=0.2, band=api.Band.CLEARED, threshold=0.3, reasons=[]),
        installation_id=10,
        pr_meta={"head_sha": "a" * 40},
    )
    github_repo_id_only = store.save_review(
        "o/r",
        33,
        "reader",
        api.Verdict(score=0.2, band=api.Band.CLEARED, threshold=0.3, reasons=[]),
        github_repo_id=20,
        pr_meta={"head_sha": "a" * 40},
    )
    app_without_head = store.save_review(
        "o/r",
        33,
        "reader",
        api.Verdict(score=0.2, band=api.Band.CLEARED, threshold=0.3, reasons=[]),
        installation_id=10,
        github_repo_id=20,
        pr_meta={"head_sha": "a" * 40},
    )

    response = client.get(
        "/v1/comparisons", headers={"X-Doug-Token": "secret"}
    )
    assert response.status_code == 200
    runs = response.json()["runs"]
    assert {run["id"] for run in runs} == {app_one, app_two, current_ci, legacy_ci}
    assert one_app_id not in {run["id"] for run in runs}
    assert github_repo_id_only not in {run["id"] for run in runs}
    assert app_without_head not in {run["id"] for run in runs}
    assert [run["path"] for run in runs].count("app") == 2
    assert [run["path"] for run in runs].count("ci") == 2
    assert next(run for run in runs if run["id"] == current_ci)["head_sha"] == "a" * 40
    assert {run["head_sha"] for run in runs} == {"a" * 40}
    covered = next(run for run in runs if run["id"] == app_one)
    assert covered["coverage"]["sent_chars"] == 10
    assert covered["coverage"]["diff_chars"] == 20


def test_comparisons_refuses_to_return_partial_evidence_when_run_cap_is_exceeded(
    tmp_path, monkeypatch
):
    """A safety bound must fail loud, never cut a comparison group.

    Returning the first N duplicate attempts would let the web layer infer a
    missing path or score delta from an incomplete ledger slice.
    """
    _comparison_db(tmp_path, monkeypatch)
    monkeypatch.setattr(store, "COMPARISON_RUN_LIMIT", 2)
    _comparison_api_review(app=True)
    _comparison_api_review(app=False)
    _comparison_api_review(app=True)

    response = client.get(
        "/v1/comparisons", headers={"X-Doug-Token": "secret"}
    )

    assert response.status_code == 413
    assert response.json() == {
        "detail": "comparison contains more than 2 runs; narrow the repo or PR limit"
    }


def test_comparisons_keeps_a_run_whose_display_metadata_is_missing(
    tmp_path, monkeypatch
):
    _comparison_db(tmp_path, monkeypatch)
    verdict = api.Verdict(
        score=0.2,
        band=api.Band.CLEARED,
        threshold=0.3,
        reasons=[],
    )
    store.save_review("o/r", 9, "deterministic", verdict, pr_meta=None)

    run = client.get(
        "/v1/comparisons", headers={"X-Doug-Token": "secret"}
    ).json()["runs"][0]
    assert run["title"] == "PR #9"
    assert run["url"] == "https://github.com/o/r/pull/9"
    assert run["head_sha"] is None
