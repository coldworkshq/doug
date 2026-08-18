import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from githubkit import AppAuthStrategy, AppInstallationAuthStrategy

from doug import app_auth

APP_ID = "4450932"
INSTALLATION_ID = 150424894


def _pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


# Generated once: key generation is the slowest thing in this file, and no
# test here needs a key that differs from any other. Nothing reaches GitHub —
# these assertions are about which credential a client carries, which is
# exactly the question a real App key must never be checked into a test to
# answer.
PEM = _pem()


def _configured(monkeypatch, pem: str = PEM) -> None:
    monkeypatch.setenv("DOUG_GITHUB_APP_ID", APP_ID)
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", pem)


def test_disabled_without_the_app_id(monkeypatch):
    """Half-configured is off, not degraded. A deployment holding the key but
    no app id cannot sign anything, and discovering that at the first webhook
    turns a config mistake into a paid-path outage."""
    monkeypatch.delenv("DOUG_GITHUB_APP_ID", raising=False)
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", PEM)
    assert not app_auth.enabled()


def test_disabled_without_the_private_key(monkeypatch):
    monkeypatch.setenv("DOUG_GITHUB_APP_ID", APP_ID)
    monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY", raising=False)
    assert not app_auth.enabled()


def test_enabled_with_both(monkeypatch):
    _configured(monkeypatch)
    assert app_auth.enabled()


def test_app_client_carries_the_app_identity(monkeypatch):
    """The JWT strategy is what makes a call the App rather than a user. A
    client built with the wrong strategy fails at GitHub with a 401 that says
    nothing about which of the two credentials was missing."""
    _configured(monkeypatch)
    gh = app_auth.app_client()
    assert isinstance(gh.auth, AppAuthStrategy)
    assert str(gh.auth.app_id) == APP_ID


def test_installation_client_carries_the_installation(monkeypatch):
    """An installation token is scoped to one installation for one hour, so
    the installation id has to travel with the client rather than being
    remembered by the caller. Getting this wrong reads another tenant's
    repositories, which is the one failure mode with no safe degradation."""
    _configured(monkeypatch)
    gh = app_auth.installation_client(INSTALLATION_ID)
    assert isinstance(gh.auth, AppInstallationAuthStrategy)
    assert gh.auth.installation_id == INSTALLATION_ID
    assert str(gh.auth.app_id) == APP_ID


def test_each_installation_gets_its_own_client(monkeypatch):
    """No caching. The worker processes jobs from many installations through
    the same process, and a shared client would carry the first tenant's token
    into every job after it."""
    _configured(monkeypatch)
    a = app_auth.installation_client(1)
    b = app_auth.installation_client(2)
    assert a is not b
    assert (a.auth.installation_id, b.auth.installation_id) == (1, 2)


def test_an_escaped_pem_is_repaired(monkeypatch):
    """Secret Manager delivers real newlines; a PEM pasted into a shell env or
    a .env file arrives with them escaped, and PyJWT rejects that with an
    opaque key-format error at the first API call rather than at startup."""
    _configured(monkeypatch, PEM.replace("\n", "\\n"))
    gh = app_auth.app_client()
    assert gh.auth.private_key == PEM


def test_clients_refuse_when_unconfigured(monkeypatch):
    """enabled() is the check callers make; this is what happens when one
    forgets. Constructing a client with a None app id would defer the failure
    to a 401 from GitHub."""
    monkeypatch.delenv("DOUG_GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY", raising=False)
    with pytest.raises(RuntimeError, match="DOUG_GITHUB_APP_ID"):
        app_auth.app_client()
    with pytest.raises(RuntimeError, match="DOUG_GITHUB_APP_ID"):
        app_auth.installation_client(INSTALLATION_ID)


def test_a_chained_client_is_collected_mid_expression_but_a_bound_one_survives(monkeypatch):
    """Characterization of githubkit, pinned because it has now cost
    production twice: the dispense identity check on 2026-08-05 (#52) and
    every adjudicator run from 2026-08-17.

    `.rest` holds its client with a weakref (`githubkit_schemas/core/rest.py`,
    `RestVersionSwitcher._github_ref`), so a construct-and-chain temporary is
    deallocated the instant `.rest` is evaluated and the NEXT attribute raises.
    Two consequences that a comment cannot enforce and this can: it fires
    before any request, so no network stub or fixture makes it go away, and
    the only fix is for the caller to bind the client to a local for the
    duration of the call. `test_client_lifetime.py` holds that line.
    """
    _configured(monkeypatch)

    with pytest.raises(RuntimeError, match="has already been collected"):
        _ = app_auth.app_client().rest.apps

    bound = app_auth.app_client()
    assert bound.rest.apps is not None
