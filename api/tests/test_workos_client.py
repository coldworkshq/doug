"""Tests for the WorkOS HTTP client.

No test in this file performs network I/O. `workos_client._send` is the
module's ONE network boundary, and every test here replaces either it or
`_request` above it with a local fake — the same posture test_session_auth.py
takes toward JWKS and test_tenancy.py takes toward GitHub.

The responses are real `httpx.Response` objects built in-process, so the
parsing under test is the parsing production runs, not a dict-shaped
approximation of it.
"""

import httpx
import pytest

from doug import workos_client


class _Fake:
    """Stands in for workos_client._request: routes on (method, path),
    records every call, and answers from a queue per route. A route with
    nothing queued is a test bug, not a 404 — it raises."""

    def __init__(self, **routes):
        # routes are keyed "GET /organizations/external_id/x" with a list of
        # httpx.Response, consumed in order (the last one repeats).
        self.routes = routes
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, method, path, *, json=None):
        self.calls.append((method, path, json))
        key = f"{method} {path}"
        queued = self.routes.get(key)
        if not queued:
            raise AssertionError(f"unexpected WorkOS call: {key}")
        return queued.pop(0) if len(queued) > 1 else queued[0]

    def paths(self) -> list[str]:
        return [f"{method} {path}" for method, path, _ in self.calls]


def _identities(*entries):
    return [httpx.Response(200, json=list(entries))]


def test_github_user_id_reads_the_idp_id_of_the_github_identity(monkeypatch):
    fake = _Fake(
        **{
            "GET /user_management/users/user_01ABC/identities": _identities(
                {"idp_id": "184352", "type": "OAuth", "provider": "GithubOAuth"}
            )
        }
    )
    monkeypatch.setattr(workos_client, "_request", fake)
    assert workos_client.github_user_id_for("user_01ABC") == "184352"


def test_github_user_id_refuses_a_non_github_identity(monkeypatch):
    """A Google identity's idp_id is a Google subject id, and comparing it
    against a GitHub user id is meaningless. Never take 'the only identity
    present' when the provider says it is not GitHub."""
    fake = _Fake(
        **{
            "GET /user_management/users/user_01ABC/identities": _identities(
                {"idp_id": "184352", "type": "OAuth", "provider": "GoogleOAuth"}
            )
        }
    )
    monkeypatch.setattr(workos_client, "_request", fake)
    assert workos_client.github_user_id_for("user_01ABC") is None


def test_github_user_id_reads_a_data_wrapped_list(monkeypatch):
    """WorkOS list endpoints answer {"data": [...]}, and the identities
    endpoint is documented as a bare array. Both shapes are accepted rather
    than one of them being guessed."""
    fake = _Fake(
        **{
            "GET /user_management/users/user_01ABC/identities": [
                httpx.Response(
                    200,
                    json={
                        "data": [
                            {"idp_id": "184352", "provider": "GithubOAuth"}
                        ],
                        "list_metadata": {},
                    },
                )
            ]
        }
    )
    monkeypatch.setattr(workos_client, "_request", fake)
    assert workos_client.github_user_id_for("user_01ABC") == "184352"


def test_github_user_id_is_none_when_the_user_has_no_identities(monkeypatch):
    fake = _Fake(
        **{"GET /user_management/users/user_01ABC/identities": [httpx.Response(200, json=[])]}
    )
    monkeypatch.setattr(workos_client, "_request", fake)
    assert workos_client.github_user_id_for("user_01ABC") is None


def test_an_upstream_failure_raises_rather_than_reading_as_no_identity(monkeypatch):
    """A 500 from WorkOS is an outage, not proof that this user has no GitHub
    identity. The endpoint renders None as a refusal and this as a 503, so
    collapsing them would tell a tenant their credentials are wrong during
    someone else's incident."""
    fake = _Fake(
        **{
            "GET /user_management/users/user_01ABC/identities": [
                httpx.Response(500, text="boom")
            ]
        }
    )
    monkeypatch.setattr(workos_client, "_request", fake)
    with pytest.raises(workos_client.WorkOSError):
        workos_client.github_user_id_for("user_01ABC")


def test_ensure_organization_reuses_an_existing_external_id(monkeypatch):
    fake = _Fake(
        **{
            "GET /organizations/external_id/gh-inst-42": [
                httpx.Response(200, json={"id": "org_live", "external_id": "gh-inst-42"})
            ]
        }
    )
    monkeypatch.setattr(workos_client, "_request", fake)
    assert workos_client.ensure_organization("drewjst", "gh-inst-42") == "org_live"
    # No create attempted: a second organization for the same installation is
    # the split-tenant failure this lookup exists to prevent.
    assert fake.paths() == ["GET /organizations/external_id/gh-inst-42"]


def test_ensure_organization_creates_when_absent(monkeypatch):
    fake = _Fake(
        **{
            "GET /organizations/external_id/gh-inst-42": [httpx.Response(404, json={})],
            "POST /organizations": [httpx.Response(201, json={"id": "org_new"})],
        }
    )
    monkeypatch.setattr(workos_client, "_request", fake)
    assert workos_client.ensure_organization("drewjst", "gh-inst-42") == "org_new"
    [(_, _, body)] = [c for c in fake.calls if c[0] == "POST"]
    assert body == {"name": "drewjst", "external_id": "gh-inst-42"}


def test_ensure_organization_recovers_from_a_lost_create_race(monkeypatch):
    """Find-or-create is inherently TOCTOU. external_id is unique at WorkOS,
    so the loser of a race gets a conflict — which is 'already done', not
    'failed', exactly as store.upsert_installation treats its own insert
    race."""
    fake = _Fake(
        **{
            "GET /organizations/external_id/gh-inst-42": [
                httpx.Response(404, json={}),
                httpx.Response(200, json={"id": "org_peer"}),
            ],
            "POST /organizations": [
                httpx.Response(409, json={"code": "organization_external_id_taken"})
            ],
        }
    )
    monkeypatch.setattr(workos_client, "_request", fake)
    assert workos_client.ensure_organization("drewjst", "gh-inst-42") == "org_peer"


def test_ensure_organization_raises_when_the_race_recovery_finds_nothing(monkeypatch):
    """A conflict with no organization behind it is not a bind we can
    complete — never return None into a caller that would write it."""
    fake = _Fake(
        **{
            "GET /organizations/external_id/gh-inst-42": [httpx.Response(404, json={})],
            "POST /organizations": [httpx.Response(409, json={})],
        }
    )
    monkeypatch.setattr(workos_client, "_request", fake)
    with pytest.raises(workos_client.WorkOSError):
        workos_client.ensure_organization("drewjst", "gh-inst-42")


def test_ensure_membership_treats_an_existing_membership_as_success(monkeypatch):
    """installation.created is replayable from GitHub's Redeliver button, so
    a second bind by the same person must not 500 on their own membership."""
    fake = _Fake(
        **{
            "POST /user_management/organization_memberships": [
                httpx.Response(409, json={"code": "organization_membership_already_exists"})
            ]
        }
    )
    monkeypatch.setattr(workos_client, "_request", fake)
    workos_client.ensure_membership("user_01ABC", "org_live")  # must not raise


def test_ensure_membership_raises_on_a_real_failure(monkeypatch):
    fake = _Fake(
        **{"POST /user_management/organization_memberships": [httpx.Response(500, text="boom")]}
    )
    monkeypatch.setattr(workos_client, "_request", fake)
    with pytest.raises(workos_client.WorkOSError):
        workos_client.ensure_membership("user_01ABC", "org_live")


def test_a_missing_api_key_raises_before_any_request_is_sent(monkeypatch):
    """Mirrors session_auth.SessionAuthNotConfigured: a deployment missing
    its WorkOS key fails loudly as a 503 rather than looking like every
    caller failing an identity check."""
    monkeypatch.delenv("WORKOS_API_KEY", raising=False)

    def _explode(*a, **k):
        raise AssertionError("network reached without an API key")

    monkeypatch.setattr(workos_client, "_send", _explode)
    with pytest.raises(workos_client.WorkOSNotConfigured):
        workos_client.github_user_id_for("user_01ABC")


def test_the_api_key_never_reaches_a_log_line_or_an_exception(monkeypatch, capsys):
    """The key is a bearer credential for every tenant's identity data. It
    rides in a header and nowhere else — not in the WorkOSError a caller may
    log, and not on stderr."""
    monkeypatch.setenv("WORKOS_API_KEY", "sk_test_do_not_leak_me")
    sent: list[dict] = []

    def _fake_send(method, url, *, headers, json):
        sent.append(headers)
        return httpx.Response(500, text="boom")

    monkeypatch.setattr(workos_client, "_send", _fake_send)
    with pytest.raises(workos_client.WorkOSError) as exc:
        workos_client.github_user_id_for("user_01ABC")

    assert sent and sent[0]["Authorization"] == "Bearer sk_test_do_not_leak_me"
    assert "sk_test_do_not_leak_me" not in str(exc.value)
    assert "sk_test_do_not_leak_me" not in capsys.readouterr().err


def test_the_external_id_is_derived_from_the_installation_and_nothing_else():
    """The org key is a function of the installation id — never a
    caller-supplied string. That is what makes org-squatting structurally
    impossible rather than defended against."""
    assert workos_client.external_id_for(150424894) == "gh-inst-150424894"


def test_ensure_membership_raises_on_a_422_that_is_not_a_duplicate(monkeypatch):
    """422 is WorkOS's general validation failure, not its 'already a member'.
    Reading every 422 as success would let an invalid organization id return
    a 204 with no membership written — a bind that looks complete and shows
    the tenant nothing."""
    fake = _Fake(
        **{
            "POST /user_management/organization_memberships": [
                httpx.Response(422, json={"code": "invalid_organization_id"})
            ]
        }
    )
    monkeypatch.setattr(workos_client, "_request", fake)
    with pytest.raises(workos_client.WorkOSError):
        workos_client.ensure_membership("user_01ABC", "org_nope")

    # The duplicate variant of the same status IS success — otherwise this
    # test would pass just by raising on every 422.
    fake = _Fake(
        **{
            "POST /user_management/organization_memberships": [
                httpx.Response(
                    422, json={"code": "organization_membership_already_exists"}
                )
            ]
        }
    )
    monkeypatch.setattr(workos_client, "_request", fake)
    workos_client.ensure_membership("user_01ABC", "org_live")
