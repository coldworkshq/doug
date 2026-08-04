from doug import store, tenancy


def _db(tmp_path, monkeypatch):
    """Same shape as tests/test_store.py::_db — a throwaway sqlite ledger."""
    url = f"sqlite:///{tmp_path}/doug.db"
    monkeypatch.setenv("DATABASE_URL", url)
    return url


def _install(installation_id: int = 150424894) -> None:
    store.upsert_installation(installation_id, "drewjst", "User", "active")


def test_mint_returns_a_prefixed_token_that_resolves(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    _install()
    token = tenancy.mint(150424894)
    assert token is not None
    assert token.startswith(tenancy.TOKEN_PREFIX)
    assert tenancy.resolve(token) == 150424894


def test_plaintext_token_is_never_stored(tmp_path, monkeypatch):
    """The token is unrecoverable by construction, not by policy. If this
    fails, a ledger dump hands over every tenant's credential."""
    _db(tmp_path, monkeypatch)
    _install()
    token = tenancy.mint(150424894)
    engine = store._get_engine()
    with engine.connect() as conn:
        stored = conn.execute(
            store.installations.select().with_only_columns(store.installations.c.token_hash)
        ).scalar_one()
    assert stored != token
    assert token not in stored


def test_minting_again_invalidates_the_previous_token(tmp_path, monkeypatch):
    """Rotation is the whole recovery story for a lost token — there is no
    other path, so the old one has to die immediately."""
    _db(tmp_path, monkeypatch)
    _install()
    first = tenancy.mint(150424894)
    second = tenancy.mint(150424894)
    assert first != second
    assert tenancy.resolve(first) is None
    assert tenancy.resolve(second) == 150424894


def test_revocation_by_nulling_the_hash(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    _install()
    token = tenancy.mint(150424894)
    engine = store._get_engine()
    with engine.begin() as conn:
        conn.execute(store.installations.update().values(token_hash=None))
    assert tenancy.resolve(token) is None


def test_resolve_rejects_junk_without_touching_storage(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    _install()
    tenancy.mint(150424894)
    assert tenancy.resolve("") is None
    assert tenancy.resolve("not-a-doug-token") is None
    assert tenancy.resolve(tenancy.TOKEN_PREFIX + "wrong") is None


def test_mint_refuses_an_installation_that_does_not_exist(tmp_path, monkeypatch):
    """No row means Doug was never installed there. Minting anyway would
    create a token that resolves to an id with no tenancy behind it."""
    _db(tmp_path, monkeypatch)
    assert tenancy.mint(999) is None


def test_disabled_storage_mints_and_resolves_nothing(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert tenancy.mint(150424894) is None
    assert tenancy.resolve("doug_anything") is None
