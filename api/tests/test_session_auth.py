"""Tests for session_auth.resolve_session.

No test in this file performs network I/O. Every JWT is minted locally
against a generated RSA key, and the JWKS client itself is monkeypatched
wholesale (session_auth._jwks) rather than exercised over HTTP — the same
posture test_tenancy.py takes toward GitHub's API via _caller_client /
app_client.
"""

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from doug import session_auth, store, tenancy

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_KEY = _PRIVATE_KEY.public_key()
# A second, unrelated key: signing with this and verifying against
# _PUBLIC_KEY is exactly what a forged/tampered token looks like.
_OTHER_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _FakeSigningKey:
    """Stands in for jwt.PyJWKClient's PyJWK — only .key is ever read."""

    def __init__(self, key):
        self.key = key


class _FakeJWKSClient:
    """Stands in for jwt.PyJWKClient. Always hands back the same test
    public key regardless of the token's kid — these tests are about what
    resolve_session does with a verified (or unverifiable) token, not about
    JWKS key rotation or kid matching."""

    def __init__(self, key=_PUBLIC_KEY):
        self._key = key

    def get_signing_key_from_jwt(self, token):
        return _FakeSigningKey(self._key)


def _use_fake_jwks(monkeypatch, key=_PUBLIC_KEY):
    monkeypatch.setattr(session_auth, "_jwks", lambda: _FakeJWKSClient(key))


def _claims(**overrides):
    """The exact claim set the production probe found on a real AuthKit
    access token — reproduced in test-fixture-note-2026-08-09.md, live-
    verified against WorkOS. Notably: no `aud`, no GitHub user id, and
    `org_id` absent unless explicitly overridden (the normal first
    sign-in state, not an edge case)."""
    now = int(time.time())
    base = {
        "iss": "https://auth.workos.com",
        "sub": "user_01ABC",
        "client_id": "client_01ABC",
        "act": None,
        "role": None,
        "roles": [],
        "permissions": [],
        "entitlements": [],
        "feature_flags": [],
        "sid": "session_01ABC",
        "jti": "01ABC",
        "iat": now,
        "exp": now + 300,
    }
    base.update(overrides)
    return base


def _token(private_key=_PRIVATE_KEY, **claim_overrides):
    return jwt.encode(_claims(**claim_overrides), private_key, algorithm="RS256")


def _db(tmp_path, monkeypatch):
    """Same shape as tests/test_tenancy.py::_db — a throwaway sqlite ledger."""
    url = f"sqlite:///{tmp_path}/doug.db"
    monkeypatch.setenv("DATABASE_URL", url)
    return url


def _install(installation_id: int = 150424894, *, org_id: str | None = None, state="active"):
    store.upsert_installation(installation_id, "drewjst", "Organization", state)
    if org_id is not None:
        engine = store._get_engine()
        with engine.begin() as conn:
            conn.execute(
                store.installations.update()
                .where(store.installations.c.installation_id == installation_id)
                .values(workos_org_id=org_id)
            )


def test_empty_bearer_is_refused_without_reaching_jwks(monkeypatch):
    """An offline check before any I/O — mirrors tenancy.resolve's
    keyformat.parse being 'zero I/O' before keys_configured() or a lookup."""
    calls = []
    monkeypatch.setattr(session_auth, "_jwks", lambda: calls.append("jwks") or _FakeJWKSClient())
    assert session_auth.resolve_session("", frozenset({1})) is None
    assert calls == []


def test_absent_org_id_fails_closed(monkeypatch):
    """org_id is present only when an organization was selected. The
    production probe confirmed it is ABSENT on a normal first sign-in with
    two installations — the common path, not an edge case. Pin the
    mechanism, not just the outcome: the installation lookup must never
    even run, so a later 'default to the first installation' regression
    would show up here as an unexpected call, not just a wrong id."""
    _use_fake_jwks(monkeypatch)
    calls = []
    monkeypatch.setattr(
        store, "installation_id_for_workos_org", lambda org_id: calls.append(org_id) or 1
    )
    token = _token()  # no org_id claim at all
    assert session_auth.resolve_session(f"Bearer {token}", frozenset({1})) is None
    assert calls == []


def test_unknown_org_id_is_refused(tmp_path, monkeypatch):
    """A well-formed, validly-signed token whose org maps to no installation
    gets nothing — not a 'pick any installation' fallback."""
    _db(tmp_path, monkeypatch)
    _use_fake_jwks(monkeypatch)
    token = _token(org_id="org_ghost")
    assert session_auth.resolve_session(f"Bearer {token}", frozenset({1})) is None


def test_expired_token_is_refused(tmp_path, monkeypatch):
    """exp is checked, not just decoded.

    Seeded exactly like test_successful_resolve_..._live_intersected_scope
    below, and the FIRST assertion pins that a normal token really does
    resolve under this seeding. That matters: without a bound installation
    and a live repo, both assertions would trivially be None regardless of
    whether exp was ever checked — org_id lookup returning None is not the
    same failure as exp verification catching an expired token, and a test
    that can't tell them apart can't fail for the right reason. The second
    assertion changes exactly one thing (exp) from the first."""
    _db(tmp_path, monkeypatch)
    _install(150424894, org_id="org_123")
    store.set_installation_repos(150424894, [(111, "drewjst/a")], replace=False)
    _use_fake_jwks(monkeypatch)

    valid = _token(org_id="org_123")
    assert session_auth.resolve_session(f"Bearer {valid}", frozenset({111})) is not None

    expired = _token(org_id="org_123", exp=int(time.time()) - 60)
    assert session_auth.resolve_session(f"Bearer {expired}", frozenset({111})) is None


def test_tampered_signature_is_refused(tmp_path, monkeypatch):
    """Signed with a DIFFERENT key than the one JWKS reports for this
    client — exactly what a forged token looks like. Must be caught at
    signature verification, not by trusting the payload.

    Same seeding-and-contrast shape as test_expired_token_is_refused, for
    the same reason: without a bound installation and a live repo the
    forged token would return None from the org_id lookup regardless of
    whether the signature was ever checked. The first assertion proves a
    genuinely-signed token of the same shape resolves; the second changes
    only the signing key."""
    _db(tmp_path, monkeypatch)
    _install(150424894, org_id="org_123")
    store.set_installation_repos(150424894, [(111, "drewjst/a")], replace=False)
    _use_fake_jwks(monkeypatch)  # reports the real public key

    valid = _token(org_id="org_123")
    assert session_auth.resolve_session(f"Bearer {valid}", frozenset({111})) is not None

    forged = _token(private_key=_OTHER_PRIVATE_KEY, org_id="org_123")
    assert session_auth.resolve_session(f"Bearer {forged}", frozenset({111})) is None


def test_session_scopes_cannot_exceed_the_enumerated_set():
    """A session has no scopes of its own. Synthesising them is inventing
    authority; the set is fixed and pinned."""
    assert set(session_auth.SESSION_SCOPES) <= {"queue:read", "receipt:read"}


def test_missing_workos_client_id_raises_configuration_exception(monkeypatch):
    """RULING 3: os.environ['WORKOS_CLIENT_ID'] would surface as an
    unhandled 500 on a misconfigured deployment. tenancy.KeysNotConfigured
    already owns this idiom (api.py turns it into a named 503) — mirror it
    rather than let a missing env var masquerade as 'every bearer token is
    forged'."""
    monkeypatch.delenv("WORKOS_CLIENT_ID", raising=False)
    monkeypatch.setattr(session_auth, "_jwks_client", None)  # don't reuse a cached client
    token = _token(org_id="org_123")
    with pytest.raises(session_auth.SessionAuthNotConfigured):
        session_auth.resolve_session(f"Bearer {token}", frozenset({1}))


def test_jwks_outage_and_forged_token_are_logged_differently(monkeypatch, capsys):
    """RULING 4: a WorkOS outage must not look identical to an attacker's
    garbage in the logs, or the first production outage is undiagnosable.
    Never log the token itself either way."""

    class _BoomJWKS:
        def get_signing_key_from_jwt(self, token):
            raise ConnectionError("workos jwks: connection refused")

    monkeypatch.setattr(session_auth, "_jwks", lambda: _BoomJWKS())
    outage_token = _token(org_id="org_123")
    assert session_auth.resolve_session(f"Bearer {outage_token}", frozenset({1})) is None
    outage_err = capsys.readouterr().err
    assert "JWKS" in outage_err
    assert outage_token not in outage_err

    _use_fake_jwks(monkeypatch)
    forged = _token(private_key=_OTHER_PRIVATE_KEY, org_id="org_123")
    assert session_auth.resolve_session(f"Bearer {forged}", frozenset({1})) is None
    forged_err = capsys.readouterr().err
    assert "verification" in forged_err
    assert "JWKS" not in forged_err
    assert forged not in forged_err


def test_successful_resolve_returns_a_session_context_with_live_intersected_scope(
    tmp_path, monkeypatch
):
    _db(tmp_path, monkeypatch)
    _install(150424894, org_id="org_live")
    store.set_installation_repos(
        150424894, [(111, "drewjst/a"), (222, "drewjst/b")], replace=False
    )
    _use_fake_jwks(monkeypatch)
    token = _token(org_id="org_live")
    ctx = session_auth.resolve_session(f"Bearer {token}", frozenset({111, 999}))
    assert ctx == tenancy.SessionContext(
        installation_id=150424894,
        repo_ids=frozenset({111}),  # 999 is claimed but not live: dropped
        scopes=session_auth.SESSION_SCOPES,
    )


def test_none_claim_yields_no_session(tmp_path, monkeypatch):
    """RULING 6: claimed_repo_ids passes straight through to
    tenancy.live_scope, which fails closed on None rather than resolving it
    to 'every repo' — a session must never get installation-wide scope."""
    _db(tmp_path, monkeypatch)
    _install(150424894, org_id="org_live")
    store.set_installation_repos(150424894, [(111, "drewjst/a")], replace=False)
    _use_fake_jwks(monkeypatch)
    token = _token(org_id="org_live")
    assert session_auth.resolve_session(f"Bearer {token}", None) is None


def test_installation_id_for_workos_org_resolves_the_bound_installation(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    _install(150424894, org_id="org_bound")
    _install(999999999, org_id=None)
    assert store.installation_id_for_workos_org("org_bound") == 150424894
    assert store.installation_id_for_workos_org("org_unbound_anywhere") is None


def test_verify_session_claims_is_strictly_weaker_than_resolve_session(monkeypatch):
    """The bind endpoint's primitive: it proves WHO is signed in and asserts
    nothing about what they may see.

    The same token drives both calls. resolve_session refuses it — no org is
    selected, so there is no tenant to resolve — while verify_session_claims
    returns the claims, which is exactly what bind needs, because bind runs
    BEFORE any organization exists. If the two ever collapse into one
    function, this test fails."""
    _use_fake_jwks(monkeypatch)
    token = _token()  # no org_id: the normal first sign-in state
    assert session_auth.resolve_session(f"Bearer {token}", frozenset({1})) is None
    claims = session_auth.verify_session_claims(f"Bearer {token}")
    assert claims is not None
    assert claims["sub"] == "user_01ABC"


def test_verify_session_claims_refuses_a_forged_or_absent_token(monkeypatch):
    """The weaker primitive is not a weaker verification: signature and exp
    are still the gate, and an empty bearer never reaches JWKS at all."""
    calls = []
    monkeypatch.setattr(session_auth, "_jwks", lambda: calls.append("jwks") or _FakeJWKSClient())
    assert session_auth.verify_session_claims("") is None
    assert calls == []

    _use_fake_jwks(monkeypatch)
    assert session_auth.verify_session_claims(f"Bearer {_token(_OTHER_PRIVATE_KEY)}") is None
    assert session_auth.verify_session_claims(
        f"Bearer {_token(exp=int(time.time()) - 60)}"
    ) is None
