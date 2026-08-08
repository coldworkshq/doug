import base64
from types import SimpleNamespace

import pytest

from doug import app_auth, store, tenancy

PEPPER_B64 = base64.b64encode(b"p" * 32).decode()
PEPPER2_B64 = base64.b64encode(b"q" * 32).decode()


def _pepper_env(monkeypatch, **extra):
    monkeypatch.setenv("DOUG_TOKEN_PEPPER", PEPPER_B64)
    for name, val in extra.items():
        monkeypatch.setenv(name, val)


def _db(tmp_path, monkeypatch):
    """Same shape as tests/test_store.py::_db — a throwaway sqlite ledger."""
    url = f"sqlite:///{tmp_path}/doug.db"
    monkeypatch.setenv("DATABASE_URL", url)
    return url


def _install(installation_id: int = 150424894) -> None:
    store.upsert_installation(installation_id, "drewjst", "User", "active")


def test_resolve_rejects_junk_without_touching_storage(monkeypatch):
    """resolve's docstring calls keyformat.parse 'offline parse+CRC (zero
    I/O)' — junk must die there, before keys_configured() or any lookup.
    Pinning the mechanism (nothing called), not just the outcome (None),
    matters here: a flood of garbage tokens must cost pure Python, never a
    database round trip or a false 'keys not configured' 503."""
    calls = []
    monkeypatch.setattr(
        tenancy, "keys_configured", lambda: calls.append("keys_configured") or True
    )
    monkeypatch.setattr(
        store, "installation_token_by_lookup", lambda lookup: calls.append(lookup) or None
    )
    assert tenancy.resolve("") is None
    assert tenancy.resolve("not-a-doug-token") is None
    assert tenancy.resolve("doug_live_wrong") is None
    assert calls == []


def test_mint_key_scopes_writes_to_the_named_installation(tmp_path, monkeypatch):
    """Pins that mint_key's INSERT carries the installation_id it was asked
    to write, not a leftover from a previous call. Nothing else in this file
    creates two installations, so a mint_key that dropped its installation_id
    binding would pass every other test here while handing one tenant's key
    authority to another.
    """
    _db(tmp_path, monkeypatch)
    _install(150424894)
    _install(999999999)
    _pepper_env(monkeypatch)

    first = tenancy.mint_key(
        150424894, repo_selection="all", repo_ids=[], label=None,
        expires_in_days=0, minted_by="drewjst",
    )
    second = tenancy.mint_key(
        999999999, repo_selection="all", repo_ids=[], label=None,
        expires_in_days=0, minted_by="drewjst",
    )

    # Each key resolves to its own installation, not the other's.
    assert tenancy.resolve(first.token).installation_id == 150424894
    assert tenancy.resolve(second.token).installation_id == 999999999


def test_mint_key_refuses_an_installation_that_does_not_exist(tmp_path, monkeypatch):
    """No row means Doug was never installed there. Minting anyway would
    create a key that resolves to an id with no tenancy behind it."""
    _db(tmp_path, monkeypatch)
    _pepper_env(monkeypatch)
    assert tenancy.mint_key(
        999, repo_selection="all", repo_ids=[], label=None,
        expires_in_days=0, minted_by="drewjst",
    ) is None


def test_disabled_storage_mints_and_resolves_nothing(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    _pepper_env(monkeypatch)
    assert tenancy.mint_key(
        150424894, repo_selection="all", repo_ids=[], label=None,
        expires_in_days=0, minted_by="drewjst",
    ) is None
    assert tenancy.resolve("doug_anything") is None


class _Boom(Exception):
    pass


def _caller(admin: bool):
    """A githubkit-shaped stub for the caller's PAT: GET /repos/{o}/{r}."""

    def _get(owner, repo):
        return SimpleNamespace(
            parsed_data=SimpleNamespace(
                permissions=SimpleNamespace(admin=admin)
            )
        )

    return SimpleNamespace(rest=SimpleNamespace(repos=SimpleNamespace(get=_get)))


def _app(installation_id=150424894, calls=None):
    """A stub for the app JWT: GET /repos/{o}/{r}/installation."""

    def _get_repo_installation(owner, repo):
        if calls is not None:
            calls.append((owner, repo))
        if installation_id is None:
            raise _Boom("not installed")
        return SimpleNamespace(parsed_data=SimpleNamespace(id=installation_id))

    return SimpleNamespace(
        rest=SimpleNamespace(
            apps=SimpleNamespace(get_repo_installation=_get_repo_installation)
        )
    )


def test_verify_admin_returns_the_installation_id(monkeypatch):
    monkeypatch.setattr(tenancy, "_caller_client", lambda pat: _caller(admin=True))
    monkeypatch.setattr(app_auth, "enabled", lambda: True)
    monkeypatch.setattr(app_auth, "app_client", lambda: _app())
    assert tenancy.verify_admin("ghp_x", "drewjst", "doug") == 150424894


def test_non_admin_pat_never_spends_dougs_github_quota(monkeypatch):
    """The ordering test, and the reason this function exists in this shape.

    GitHub's REST quota is 5,000/hr and shared across every Doug session; it
    was exhausted twice on 2026-08-02. The app-JWT call spends DOUG'S quota,
    the PAT call spends the CALLER'S. This endpoint is public, so if the app
    call ran first an anonymous caller would have a loop that drains the
    quota the review path needs to mint installation tokens. Assert on the
    empty call list, not just the return value — a refactor that reorders
    the two calls still returns None here and would slip through.
    """
    app_calls = []
    monkeypatch.setattr(tenancy, "_caller_client", lambda pat: _caller(admin=False))
    monkeypatch.setattr(app_auth, "enabled", lambda: True)
    monkeypatch.setattr(app_auth, "app_client", lambda: _app(calls=app_calls))
    assert tenancy.verify_admin("ghp_x", "drewjst", "doug") is None
    assert app_calls == []


def test_unreadable_repo_never_spends_dougs_quota(monkeypatch):
    """A PAT that cannot see the repo at all takes the same early exit."""
    app_calls = []

    def _explode(pat):
        raise _Boom("404")

    monkeypatch.setattr(tenancy, "_caller_client", _explode)
    monkeypatch.setattr(app_auth, "enabled", lambda: True)
    monkeypatch.setattr(app_auth, "app_client", lambda: _app(calls=app_calls))
    assert tenancy.verify_admin("ghp_x", "drewjst", "doug") is None
    assert app_calls == []


def test_admin_but_doug_not_installed(monkeypatch):
    monkeypatch.setattr(tenancy, "_caller_client", lambda pat: _caller(admin=True))
    monkeypatch.setattr(app_auth, "enabled", lambda: True)
    monkeypatch.setattr(app_auth, "app_client", lambda: _app(installation_id=None))
    assert tenancy.verify_admin("ghp_x", "drewjst", "doug") is None


def test_missing_permissions_block_is_not_admin(monkeypatch):
    """githubkit models an absent field as a sentinel, not None. Anything
    that is not exactly True is 'not admin' — the safe direction to be
    wrong in is refuse, the same choice worker._skip_reason makes for forks."""
    caller = SimpleNamespace(
        rest=SimpleNamespace(
            repos=SimpleNamespace(
                get=lambda owner, repo: SimpleNamespace(parsed_data=SimpleNamespace())
            )
        )
    )
    monkeypatch.setattr(tenancy, "_caller_client", lambda pat: caller)
    monkeypatch.setattr(app_auth, "enabled", lambda: True)
    monkeypatch.setattr(app_auth, "app_client", lambda: _app())
    assert tenancy.verify_admin("ghp_x", "drewjst", "doug") is None


def test_app_path_disabled_verifies_nothing(monkeypatch):
    monkeypatch.setattr(tenancy, "_caller_client", lambda pat: _caller(admin=True))
    monkeypatch.setattr(app_auth, "enabled", lambda: False)
    assert tenancy.verify_admin("ghp_x", "drewjst", "doug") is None


def test_verify_admin_logs_why_it_denied_without_leaking_the_pat(monkeypatch, capsys):
    """The caller gets an undifferentiated 404 on purpose — that is the
    no-existence-leak property. But an operator still has to tell a GitHub
    outage from a genuine refusal, and before this the two were identical
    silence. Doug's own review of PR #48 flagged exactly that.

    Both halves matter: the cause reaches stderr, and the PAT does not.
    """
    monkeypatch.setattr(app_auth, "enabled", lambda: True)
    monkeypatch.setattr(app_auth, "app_client", lambda: _app())

    def _explode(pat):
        raise _Boom("502 Bad Gateway")

    monkeypatch.setattr(tenancy, "_caller_client", _explode)
    assert tenancy.verify_admin("ghp_SUPERSECRET", "drewjst", "doug") is None

    err = capsys.readouterr().err
    assert "drewjst/doug" in err
    assert "caller check" in err
    assert "502 Bad Gateway" in err
    assert "ghp_SUPERSECRET" not in err, "the PAT must never reach the log"


def test_verify_admin_logs_a_failing_installation_lookup(monkeypatch, capsys):
    """The more valuable of the two lines: a 404 here is the ordinary
    not-installed case, so anything else means Doug's own app credentials or
    quota are in trouble and nothing else in the system reports it.
    """
    monkeypatch.setattr(tenancy, "_caller_client", lambda pat: _caller(admin=True))
    monkeypatch.setattr(app_auth, "enabled", lambda: True)
    monkeypatch.setattr(app_auth, "app_client", lambda: _app(installation_id=None))

    assert tenancy.verify_admin("ghp_x", "drewjst", "doug") is None

    err = capsys.readouterr().err
    assert "installation lookup" in err
    assert "drewjst/doug" in err


def test_hash_secret_is_stable_and_version_selects_the_pepper(monkeypatch):
    _pepper_env(monkeypatch, DOUG_TOKEN_PEPPER_V2=PEPPER2_B64)
    a = tenancy.hash_secret("s3cret", 1)
    assert a == tenancy.hash_secret("s3cret", 1)
    assert a != tenancy.hash_secret("s3cret", 2)
    assert tenancy._current_hash_version() == 2


def test_unknown_hash_version_fails_closed(monkeypatch):
    _pepper_env(monkeypatch)
    assert tenancy.hash_secret("s3cret", 7) is None


def test_pepper_must_be_exactly_32_bytes_of_valid_base64(monkeypatch):
    monkeypatch.setenv("DOUG_TOKEN_PEPPER", base64.b64encode(b"short").decode())
    assert not tenancy.keys_configured()
    monkeypatch.setenv("DOUG_TOKEN_PEPPER", "not!!base64@@")
    assert not tenancy.keys_configured()
    monkeypatch.delenv("DOUG_TOKEN_PEPPER", raising=False)
    assert not tenancy.keys_configured()
    _pepper_env(monkeypatch)
    assert tenancy.keys_configured()


def test_pepper_tolerates_the_trailing_newline_every_secret_pipeline_adds(monkeypatch):
    """print() | gcloud secrets create stores 'base64\\n', and
    b64decode(validate=True) refuses the newline — prod served 503s on
    every mint until the secret was re-cut (2026-08-05, the isolation-proof
    run). Surrounding whitespace carries no entropy and no meaning; strip
    it rather than making every operator pipeline newline-perfect."""
    monkeypatch.setenv("DOUG_TOKEN_PEPPER", PEPPER_B64 + "\n")
    assert tenancy.keys_configured()
    assert tenancy.hash_secret("s3cret", 1) == tenancy.hash_secret("s3cret", 1)
    monkeypatch.setenv("DOUG_TOKEN_PEPPER", "  " + PEPPER_B64 + "  \n")
    assert tenancy.keys_configured()


def _org_caller(login="drewjst", role="admin", state="active", membership_raises=False):
    """Stub for the caller's PAT: GET /user and GET /user/memberships/orgs/{org}."""

    def _get_authenticated():
        return SimpleNamespace(parsed_data=SimpleNamespace(login=login))

    def _membership(org):
        if membership_raises:
            raise _Boom("404 not a member")
        return SimpleNamespace(parsed_data=SimpleNamespace(role=role, state=state))

    return SimpleNamespace(
        rest=SimpleNamespace(
            users=SimpleNamespace(get_authenticated=_get_authenticated),
            orgs=SimpleNamespace(get_membership_for_authenticated_user=_membership),
        )
    )


def _org_app(installation_id=150424894, calls=None):
    """Stub for the app JWT: org/user installation lookups."""

    def _get_org_installation(org):
        if calls is not None:
            calls.append(("org", org))
        return SimpleNamespace(parsed_data=SimpleNamespace(id=installation_id))

    def _get_user_installation(username):
        if calls is not None:
            calls.append(("user", username))
        return SimpleNamespace(parsed_data=SimpleNamespace(id=installation_id))

    return SimpleNamespace(
        rest=SimpleNamespace(
            apps=SimpleNamespace(
                get_org_installation=_get_org_installation,
                get_user_installation=_get_user_installation,
            )
        )
    )


def test_org_admin_proof_mints_for_the_org(monkeypatch):
    monkeypatch.setattr(tenancy, "_caller_client", lambda pat: _org_caller())
    monkeypatch.setattr(app_auth, "enabled", lambda: True)
    monkeypatch.setattr(app_auth, "app_client", lambda: _org_app())
    assert tenancy.verify_org_admin("ghp_x", "acme") == 150424894


def test_org_member_but_not_admin_is_refused_before_dougs_quota(monkeypatch):
    """Same load-bearing order as verify_admin: the membership check is the
    caller's quota; a non-admin must never reach the app-JWT call."""
    app_calls = []
    monkeypatch.setattr(tenancy, "_caller_client", lambda pat: _org_caller(role="member"))
    monkeypatch.setattr(app_auth, "enabled", lambda: True)
    monkeypatch.setattr(app_auth, "app_client", lambda: _org_app(calls=app_calls))
    assert tenancy.verify_org_admin("ghp_x", "acme") is None
    assert app_calls == []


def test_user_install_proof_is_pat_owner_equals_owner(monkeypatch):
    """For a User-type install the account owner IS the only admin. The
    login match is case-insensitive because GitHub logins are."""
    monkeypatch.setattr(
        tenancy, "_caller_client",
        lambda pat: _org_caller(login="DrewJST", membership_raises=True),
    )
    monkeypatch.setattr(app_auth, "enabled", lambda: True)
    monkeypatch.setattr(app_auth, "app_client", lambda: _org_app())
    assert tenancy.verify_org_admin("ghp_x", "drewjst") == 150424894


def test_stranger_matches_neither_login_nor_membership(monkeypatch):
    app_calls = []
    monkeypatch.setattr(
        tenancy, "_caller_client",
        lambda pat: _org_caller(login="mallory", membership_raises=True),
    )
    monkeypatch.setattr(app_auth, "enabled", lambda: True)
    monkeypatch.setattr(app_auth, "app_client", lambda: _org_app(calls=app_calls))
    assert tenancy.verify_org_admin("ghp_x", "acme") is None
    assert app_calls == []


def test_verify_org_admin_logs_why_it_denied_without_leaking_the_pat(monkeypatch, capsys):
    """Sibling of test_verify_admin_logs_why_it_denied_without_leaking_the_pat
    for the org-admin membership-check exception path: an operator still
    needs to tell a GitHub outage from a genuine refusal, and the PAT must
    never be part of how they learn it."""
    monkeypatch.setattr(
        tenancy, "_caller_client",
        lambda pat: _org_caller(login="mallory", membership_raises=True),
    )

    assert tenancy.verify_org_admin("ghp_SUPERSECRET", "acme") is None

    err = capsys.readouterr().err
    assert "acme" in err
    assert "membership check" in err
    assert "ghp_SUPERSECRET" not in err, "the PAT must never reach the log"


def test_repos_proof_requires_one_installation(monkeypatch):
    """Two repos proving to two different installations is a cross-tenant
    key request; refuse before minting anything."""
    ids = iter([150424894, 999999999])
    monkeypatch.setattr(
        tenancy, "verify_admin", lambda pat, owner, repo: next(ids)
    )
    assert tenancy.verify_repos_admin("ghp_x", [("acme", "a"), ("acme", "b")]) is None


def test_repos_proof_requires_a_single_owner_before_any_call(monkeypatch):
    calls = []
    monkeypatch.setattr(
        tenancy, "verify_admin",
        lambda pat, owner, repo: calls.append((owner, repo)) or 150424894,
    )
    assert tenancy.verify_repos_admin("ghp_x", [("acme", "a"), ("evil", "b")]) is None
    assert calls == [], "mixed owners must not spend anyone's quota"


def test_mint_key_appends_and_never_disturbs_existing_keys(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    _install()
    _pepper_env(monkeypatch)
    first = tenancy.mint_key(
        150424894, repo_selection="all", repo_ids=[], label=None,
        expires_in_days=0, minted_by="drewjst",
    )
    second = tenancy.mint_key(
        150424894, repo_selection="selected", repo_ids=[111], label="ci",
        expires_in_days=90, minted_by="drewjst",
    )
    assert first.token != second.token
    assert first.token.startswith("doug_live_")
    assert second.expires_at is not None and first.expires_at is None
    assert store.installation_token_repo_ids(second.token_id) == {111}
    # Both rows live: nothing rotated.
    from doug import keyformat
    assert store.installation_token_by_lookup(keyformat.parse(first.token).lookup) is not None


def test_mint_key_without_pepper_raises_keys_not_configured(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    _install()
    monkeypatch.delenv("DOUG_TOKEN_PEPPER", raising=False)
    with pytest.raises(tenancy.KeysNotConfigured):
        tenancy.mint_key(
            150424894, repo_selection="all", repo_ids=[], label=None,
            expires_in_days=0, minted_by="drewjst",
        )


def test_mint_key_stores_only_the_peppered_hash(tmp_path, monkeypatch):
    """The plaintext-never-stored property, restated for the new schema."""
    _db(tmp_path, monkeypatch)
    _install()
    _pepper_env(monkeypatch)
    minted = tenancy.mint_key(
        150424894, repo_selection="all", repo_ids=[], label=None,
        expires_in_days=0, minted_by="drewjst",
    )
    from doug import keyformat
    parsed = keyformat.parse(minted.token)
    row = store.installation_token_by_lookup(parsed.lookup)
    assert parsed.secret not in row["token_hash"]
    assert minted.token not in row["token_hash"]
    assert row["token_hash"] == tenancy.hash_secret(parsed.secret, row["hash_version"])


def _minted_all(monkeypatch, tmp_path, installation_id=150424894):
    _db(tmp_path, monkeypatch)
    _install(installation_id)
    _pepper_env(monkeypatch)
    return tenancy.mint_key(
        installation_id, repo_selection="all", repo_ids=[], label=None,
        expires_in_days=0, minted_by="drewjst",
    )


def test_resolve_returns_a_context_for_a_live_key(tmp_path, monkeypatch):
    minted = _minted_all(monkeypatch, tmp_path)
    ctx = tenancy.resolve(minted.token)
    assert ctx.installation_id == 150424894
    assert ctx.token_id == minted.token_id
    assert ctx.repo_ids is None  # 'all' — filter by installation only
    assert "queue:read" in ctx.scopes


def test_resolve_rejects_wrong_secret_same_lookup(tmp_path, monkeypatch):
    """Right lookup + wrong secret must die at the HMAC compare."""
    minted = _minted_all(monkeypatch, tmp_path)
    from doug import keyformat
    parsed = keyformat.parse(minted.token)
    forged_secret = ("A" * keyformat.SECRET_LEN)
    forged = (
        keyformat.PREFIX + parsed.lookup + "_" + forged_secret
        + keyformat._crc(parsed.lookup, forged_secret)
    )
    assert tenancy.resolve(forged) is None


def test_resolve_rejects_revoked_and_expired(tmp_path, monkeypatch):
    from datetime import UTC, datetime
    minted = _minted_all(monkeypatch, tmp_path)
    engine = store._get_engine()
    with engine.begin() as conn:
        conn.execute(
            store.installation_tokens.update()
            .where(store.installation_tokens.c.id == minted.token_id)
            .values(revoked_at=datetime.now(UTC))
        )
    assert tenancy.resolve(minted.token) is None
    second = tenancy.mint_key(
        150424894, repo_selection="all", repo_ids=[], label=None,
        expires_in_days=1, minted_by="drewjst",
    )
    with engine.begin() as conn:
        conn.execute(
            store.installation_tokens.update()
            .where(store.installation_tokens.c.id == second.token_id)
            .values(expires_at=datetime(2020, 1, 1, tzinfo=UTC))
        )
    assert tenancy.resolve(second.token) is None


def test_uninstall_kills_every_key_structurally(tmp_path, monkeypatch):
    """MT2. resolve reads installations.state LIVE; no revocation write is
    needed for an uninstall to end access on the very next request."""
    minted = _minted_all(monkeypatch, tmp_path)
    assert tenancy.resolve(minted.token) is not None
    store.upsert_installation(150424894, "drewjst", "User", "deleted")
    assert tenancy.resolve(minted.token) is None
    store.upsert_installation(150424894, "drewjst", "User", "suspended")
    assert tenancy.resolve(minted.token) is None
    store.upsert_installation(150424894, "drewjst", "User", "active")
    assert tenancy.resolve(minted.token) is not None, "unsuspend restores, no key churn"


def test_selected_key_intersects_against_the_live_repo_ledger(tmp_path, monkeypatch):
    """The frozen selection is a CLAIM; installation_repos is the authority.
    A repo removed from the installation vanishes from the key, and a key
    whose every repo is gone resolves to nothing (empty intersection fails
    closed, lema's rule)."""
    _db(tmp_path, monkeypatch)
    _install()
    _pepper_env(monkeypatch)
    store.set_installation_repos(150424894, [(111, "drewjst/a"), (222, "drewjst/b")], replace=False)
    minted = tenancy.mint_key(
        150424894, repo_selection="selected", repo_ids=[111, 222], label=None,
        expires_in_days=0, minted_by="drewjst",
    )
    assert tenancy.resolve(minted.token).repo_ids == frozenset({111, 222})
    store.set_installation_repos(150424894, [(222, "drewjst/b")], replace=False, state="removed")
    assert tenancy.resolve(minted.token).repo_ids == frozenset({111})
    store.set_installation_repos(150424894, [(111, "drewjst/a")], replace=False, state="removed")
    assert tenancy.resolve(minted.token) is None


def test_resolve_ignores_non_key_tokens_and_flags_unconfigured_keys(tmp_path, monkeypatch):
    """Junk and operator tokens return None (no pepper involved). A token
    that IS key-shaped while no pepper is configured raises — the route
    turns that into 503, because 'we cannot verify anything' must not read
    as 'your key is bad'."""
    minted = _minted_all(monkeypatch, tmp_path)
    assert tenancy.resolve("not-a-token") is None
    assert tenancy.resolve("doug_" + "x" * 43) is None
    monkeypatch.delenv("DOUG_TOKEN_PEPPER", raising=False)
    with pytest.raises(tenancy.KeysNotConfigured):
        tenancy.resolve(minted.token)


def test_resolve_runs_a_dummy_hmac_on_lookup_miss(tmp_path, monkeypatch):
    """A miss must be timing-indistinguishable from a wrong secret. Pin the
    mechanism (hash_secret called even when no row matched), not the clock."""
    _db(tmp_path, monkeypatch)
    _install()
    _pepper_env(monkeypatch)
    calls = []
    real = tenancy.hash_secret
    monkeypatch.setattr(
        tenancy, "hash_secret", lambda s, v: calls.append(v) or real(s, v)
    )
    from doug import keyformat
    ghost = keyformat.generate()  # never inserted → guaranteed lookup miss
    assert tenancy.resolve(ghost.token) is None
    assert calls, "lookup miss must still burn one HMAC"


def test_new_keys_mint_both_scopes(tmp_path, monkeypatch):
    """Capabilities are granted explicitly, never inherited.

    /v1/queue's own comment says the scopes column exists so a receipts-only
    key cannot silently pick up queue access; the discipline runs both ways.
    """
    minted = _minted_all(monkeypatch, tmp_path)
    ctx = tenancy.resolve(minted.token)
    assert set(ctx.scopes) == {"queue:read", "receipt:read"}
