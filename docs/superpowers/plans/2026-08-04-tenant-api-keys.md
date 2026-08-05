# Tenant API Keys Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single `installations.token_hash` credential with an `installation_tokens` keys table (repo-selection model) per `docs/superpowers/specs/2026-08-04-tenant-api-keys-design.md`, closing MT1, MT2, MT4 and MT5.

**Architecture:** A pure format module (`keyformat.py`) generates/parses `doug_live_` tokens; `tenancy.py` gains peppered-HMAC hashing, selection-aware mint proofs, and a resolve that returns a `TokenContext` after intersecting the key's frozen repo selection against the live ledger; `store.py` gains two tables and accessors; `api.py` swaps the dispense/queue endpoints onto them and adds list/revoke.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy Core, githubkit, pytest. Tests run from `api/`: `cd api && python -m pytest tests/ -x -q`.

## Global Constraints

Copied from the spec — every task inherits these:

- Token format: `doug_live_<lookup:8>_<secret:43><crc:6>`, base62; `doug_test_` reserved and rejected; legacy `doug_` tokens rejected by the prefix check.
- Hashing: HMAC-SHA256(secret, pepper), hex; pepper = `DOUG_TOKEN_PEPPER` (base64, exactly 32 bytes); `hash_version` n → `DOUG_TOKEN_PEPPER_V<n>` (`DOUG_TOKEN_PEPPER` ≡ V1); unknown version fails closed; pepper unset → mint **and** resolve raise → routes 503.
- Every mint/list/revoke verification failure renders as uniform 404. Queue token failures stay 401.
- THE CALL ORDER IS LOAD-BEARING: on every proof path, PAT calls (caller's quota) run before any app-JWT call (Doug's quota). `test_non_admin_pat_never_spends_dougs_github_quota` pins this and must keep passing.
- Mint appends rows — it never rotates or invalidates an existing key.
- Caps: 20 repos per `selected` mint; 30 mints/installation/UTC-day, **fail-open** (a counting error logs and allows).
- `expires_in_days` 0/omitted = durable; range 0–366; out of range → 404.
- Repo authority is `github_repo_id`; `full_name` is display-only. No cross-table FKs (repo convention).
- Timestamps: store tz-aware UTC (`datetime.now(UTC)`); sqlite returns them naive, so every Python-side comparison must normalize with `.replace(tzinfo=UTC)` when `tzinfo is None`.
- Handlers log `token_id`/`lookup`/`last4` only — never the full token, never the secret, never the PAT.
- `tenancy.py` stays free of FastAPI imports (MCP-garden constraint, `tenancy.py:1-7`).
- Migration discipline (`api/doug/migrations.py:1-15`): every column change on an *existing* table appears in both the `Table()` definition and a migration; new tables come from `create_all()` only. `ALTER TABLE` on a missing table must never reach `_run` (the PR #48 crash-loop lesson).

## File Structure

- Create: `api/doug/keyformat.py` — pure token format (generate/parse/CRC), no imports from the app.
- Modify: `api/doug/tenancy.py` — pepper/hash helpers, `KeysNotConfigured`, `TokenContext`, `mint_key`, `verify_org_admin`, `verify_repos_admin`, new `resolve`; old `mint`/`_hash`/`TOKEN_PREFIX` deleted by Task 6.
- Modify: `api/doug/store.py` — `installation_tokens` + `installation_token_repos` tables; accessors; `token_hash` column removed from `installations`; `latest_reviews(repo_ids=...)`.
- Modify: `api/doug/migrations.py` — migration 6 (drop `installations.token_hash`), `_SATISFIED` extension.
- Modify: `api/doug/api.py` — dispense/queue/list/revoke endpoints, uninstall bulk-revoke, startup drift warning.
- Modify: `api/deploy/gcp.sh` — pepper secret creation + binding.
- Create: `docs/OPERATIONS.md` — break-glass revoke, pepper rotation, MT0 redelivery.
- Tests: `api/tests/test_keyformat.py` (new), `api/tests/test_tenancy.py`, `api/tests/test_store.py`, `api/tests/test_api.py`.

---

## Slice A — schema + format + mint/resolve (closes MT1, MT2, MT5)

### Task 1: `keyformat.py` — the token format

**Files:**
- Create: `api/doug/keyformat.py`
- Test: `api/tests/test_keyformat.py`

**Interfaces:**
- Consumes: stdlib only (`secrets`, `zlib`).
- Produces: `PREFIX: str = "doug_live_"`, `TEST_PREFIX: str = "doug_test_"`, `LOOKUP_LEN=8`, `SECRET_LEN=43`, `CRC_LEN=6`, `Minted(NamedTuple: token, lookup, secret, last4)`, `Parsed(NamedTuple: lookup, secret)`, `generate() -> Minted`, `parse(token: str) -> Parsed | None`.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_keyformat.py
from doug import keyformat


def test_generate_round_trips_through_parse():
    minted = keyformat.generate()
    assert minted.token.startswith(keyformat.PREFIX)
    parsed = keyformat.parse(minted.token)
    assert parsed is not None
    assert parsed.lookup == minted.lookup
    assert parsed.secret == minted.secret
    assert minted.last4 == minted.secret[-4:]


def test_lookup_and_secret_have_the_specified_lengths():
    minted = keyformat.generate()
    assert len(minted.lookup) == keyformat.LOOKUP_LEN == 8
    assert len(minted.secret) == keyformat.SECRET_LEN == 43


def test_parse_rejects_a_flipped_character_via_crc():
    """The CRC is a scanner-noise filter with zero security weight, but it
    must actually filter: a corrupted token dies offline, before any DB hit."""
    token = keyformat.generate().token
    # Flip one character inside the secret region (after prefix + lookup + '_').
    i = len(keyformat.PREFIX) + keyformat.LOOKUP_LEN + 1 + 5
    flipped = token[:i] + ("A" if token[i] != "A" else "B") + token[i + 1 :]
    assert keyformat.parse(flipped) is None


def test_parse_rejects_the_reserved_test_prefix():
    """doug_test_ must hard-fail rather than fall through to any other
    verifier — the same guard lema's ChainVerifier polices independently."""
    minted = keyformat.generate()
    impostor = keyformat.TEST_PREFIX + minted.token[len(keyformat.PREFIX) :]
    assert keyformat.parse(impostor) is None


def test_parse_rejects_legacy_and_junk_shapes():
    assert keyformat.parse("") is None
    assert keyformat.parse("doug_" + "x" * 43) is None          # PR #48 legacy shape
    assert keyformat.parse(keyformat.PREFIX) is None            # nothing after prefix
    assert keyformat.parse(keyformat.PREFIX + "short_x") is None
    minted = keyformat.generate()
    assert keyformat.parse(minted.token + "z") is None          # wrong tail length
    assert keyformat.parse(minted.token.replace("_", "-", 2)) is None


def test_two_generates_never_collide():
    a, b = keyformat.generate(), keyformat.generate()
    assert a.token != b.token
    assert a.lookup != b.lookup
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && python -m pytest tests/test_keyformat.py -v`
Expected: FAIL — `ModuleNotFoundError` / `ImportError: cannot import name 'keyformat'`

- [ ] **Step 3: Write the module**

```python
# api/doug/keyformat.py
"""The doug_live_ token format: generate, parse, offline checksum.

Pure functions over stdlib only — no storage, no config. The format follows
GitHub's token-format design (greppable literal prefix + base62 + CRC32 tail)
so secret scanners get near-zero false positives without a database hit. The
CRC carries ZERO security weight: it filters corruption and scanner noise,
nothing else. Security lives in the 256-bit secret and the peppered HMAC
stored by tenancy.py.
"""

import secrets
import zlib
from typing import NamedTuple

PREFIX = "doug_live_"
# Reserved for a future sandbox tier. parse() rejects it TODAY so a test key
# can never fall through to a different verifier that treats it as live.
TEST_PREFIX = "doug_test_"

_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
LOOKUP_LEN = 8   # plaintext key id: btree point-lookup, safe in logs and UI
SECRET_LEN = 43  # 43 base62 chars ≈ 256 bits of entropy
CRC_LEN = 6      # CRC32 max fits in 6 base62 chars (62^6 > 2^32)


class Minted(NamedTuple):
    token: str
    lookup: str
    secret: str
    last4: str


class Parsed(NamedTuple):
    lookup: str
    secret: str


def _b62(n: int, width: int) -> str:
    out = []
    while n:
        n, r = divmod(n, 62)
        out.append(_ALPHABET[r])
    return ("".join(reversed(out)) or "0").rjust(width, "0")


def _crc(lookup: str, secret: str) -> str:
    return _b62(zlib.crc32((lookup + secret).encode()), CRC_LEN)


def _rand(width: int) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(width))


def generate() -> Minted:
    lookup = _rand(LOOKUP_LEN)
    secret = _rand(SECRET_LEN)
    token = f"{PREFIX}{lookup}_{secret}{_crc(lookup, secret)}"
    return Minted(token=token, lookup=lookup, secret=secret, last4=secret[-4:])


def parse(token: str) -> Parsed | None:
    """A structurally valid doug_live_ token's parts, or None.

    Rejection order matters only for TEST_PREFIX: it must be recognized and
    refused explicitly, never treated as 'not ours'.
    """
    if token.startswith(TEST_PREFIX):
        return None
    if not token.startswith(PREFIX):
        return None
    rest = token[len(PREFIX):]
    lookup, sep, tail = rest.partition("_")
    if sep != "_" or len(lookup) != LOOKUP_LEN or len(tail) != SECRET_LEN + CRC_LEN:
        return None
    secret, crc = tail[:SECRET_LEN], tail[SECRET_LEN:]
    if any(c not in _ALPHABET for c in lookup + secret + crc):
        return None
    if crc != _crc(lookup, secret):
        return None
    return Parsed(lookup=lookup, secret=secret)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && python -m pytest tests/test_keyformat.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add api/doug/keyformat.py api/tests/test_keyformat.py
git commit -m "feat: doug_live_ token format — prefix, base62, offline CRC"
```

### Task 2: Schema — two tables, migration 6, core accessors

**Files:**
- Modify: `api/doug/store.py` (installations Table def ~`:174-187`; new Tables after `installation_repos` ~`:199`; new accessors after `active_repos` ~`:1264`)
- Modify: `api/doug/migrations.py` (`MIGRATIONS` list `:39`, `_SATISFIED` `:200`)
- Test: `api/tests/test_store.py` (append), `api/tests/test_tenancy.py` (two old tests deleted here)

**Interfaces:**
- Consumes: nothing new.
- Produces (all in `store`):
  - Tables `installation_tokens`, `installation_token_repos` (columns exactly as below).
  - `insert_installation_token(installation_id: int, *, token_lookup: str, token_hash: str, hash_version: int, last4: str, label: str | None, repo_selection: str, scopes: list[str], minted_by: str, expires_at: datetime | None) -> int | None` — returns new row id; `None` when storage is off **or the installation row does not exist** (the PR #48 refusal semantics: no row = refusal).
  - `set_installation_token_repos(token_id: int, repo_ids: list[int]) -> None`
  - `installation_token_by_lookup(token_lookup: str) -> dict | None` — token row joined to `installations.state` as key `installation_state`; `expires_at`/`revoked_at` normalized to tz-aware UTC.
  - `installation_token_repo_ids(token_id: int) -> set[int]`
  - `count_installation_tokens_minted_since(installation_id: int, since: datetime) -> int | None` — `None` on ANY error (fail-open cap).
  - `touch_installation_token_last_used(token_id: int) -> None` — best-effort, ≥60s throttle, swallows errors.

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_store.py` (it already has a `_db(tmp_path, monkeypatch)` helper — reuse it):

```python
# --- installation_tokens (tenant API keys spec, 2026-08-04) ---
from datetime import UTC, datetime, timedelta


def _seed_install(installation_id=150424894):
    store.upsert_installation(installation_id, "drewjst", "User", "active")


def test_insert_installation_token_requires_an_installation_row(tmp_path, monkeypatch):
    """No installations row means Doug was never installed there — a key
    minted anyway would resolve to an id no tenancy backs (PR #48 semantics,
    kept)."""
    _db(tmp_path, monkeypatch)
    assert (
        store.insert_installation_token(
            999,
            token_lookup="AAAAAAAA",
            token_hash="ab" * 32,
            hash_version=1,
            last4="wxyz",
            label=None,
            repo_selection="all",
            scopes=["queue:read"],
            minted_by="drewjst",
            expires_at=None,
        )
        is None
    )


def test_token_row_round_trips_with_installation_state(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    _seed_install()
    token_id = store.insert_installation_token(
        150424894,
        token_lookup="AAAAAAAA",
        token_hash="ab" * 32,
        hash_version=1,
        last4="wxyz",
        label="ci",
        repo_selection="selected",
        scopes=["queue:read"],
        minted_by="drewjst",
        expires_at=datetime.now(UTC) + timedelta(days=90),
    )
    assert isinstance(token_id, int)
    store.set_installation_token_repos(token_id, [111, 222])
    row = store.installation_token_by_lookup("AAAAAAAA")
    assert row["id"] == token_id
    assert row["installation_state"] == "active"
    assert row["repo_selection"] == "selected"
    assert row["hash_version"] == 1
    assert row["expires_at"].tzinfo is not None, "sqlite naive datetimes must be normalized"
    assert store.installation_token_repo_ids(token_id) == {111, 222}
    assert store.installation_token_by_lookup("NOPENOPE") is None


def test_second_token_does_not_disturb_the_first(tmp_path, monkeypatch):
    """Mint appends. The single-column model's silent rotation was half of
    MT5; two rows must coexist."""
    _db(tmp_path, monkeypatch)
    _seed_install()
    kw = dict(
        token_hash="ab" * 32, hash_version=1, last4="wxyz", label=None,
        repo_selection="all", scopes=["queue:read"], minted_by="drewjst",
        expires_at=None,
    )
    a = store.insert_installation_token(150424894, token_lookup="AAAAAAAA", **kw)
    b = store.insert_installation_token(150424894, token_lookup="BBBBBBBB", **kw)
    assert a != b
    assert store.installation_token_by_lookup("AAAAAAAA")["id"] == a
    assert store.installation_token_by_lookup("BBBBBBBB")["id"] == b


def test_mint_count_since_counts_only_this_installation(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    _seed_install(150424894)
    _seed_install(999999999)
    kw = dict(
        token_hash="ab" * 32, hash_version=1, last4="wxyz", label=None,
        repo_selection="all", scopes=["queue:read"], minted_by="drewjst",
        expires_at=None,
    )
    store.insert_installation_token(150424894, token_lookup="AAAAAAAA", **kw)
    store.insert_installation_token(999999999, token_lookup="BBBBBBBB", **kw)
    midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    assert store.count_installation_tokens_minted_since(150424894, midnight) == 1


def test_mint_count_returns_none_when_storage_off(monkeypatch):
    """None, not 0: the caller treats None as 'cannot count' and allows —
    the cap is fail-open by spec."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert store.count_installation_tokens_minted_since(150424894, datetime.now(UTC)) is None


def test_migration_6_applies_on_fresh_and_legacy_shapes(tmp_path, monkeypatch):
    """Fresh DB: create_all builds installations WITHOUT token_hash, so the
    DROP finds its work done and must not raise (the 'satisfied, not failed'
    rule). Legacy DB: the column exists and is dropped."""
    from sqlalchemy import create_engine, inspect
    from doug import migrations

    _db(tmp_path, monkeypatch)
    store._get_engine()  # create_all + apply on the fresh path — must not raise
    engine = create_engine(f"sqlite:///{tmp_path}/legacy.db")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE installations (id INTEGER PRIMARY KEY, "
            "installation_id BIGINT NOT NULL UNIQUE, account_login VARCHAR(200), "
            "account_type VARCHAR(20), state VARCHAR(20) NOT NULL, "
            "updated_at TIMESTAMP NOT NULL, token_hash TEXT)"
        )
    migrations.apply(engine)
    assert "token_hash" not in {c["name"] for c in inspect(engine).get_columns("installations")}
```

Also DELETE these two tests from `api/tests/test_tenancy.py` now — they pin the
single-column model this task removes, and nothing else reads `token_hash`:
`test_minting_again_invalidates_the_previous_token` (`:41-50`) and
`test_revocation_by_nulling_the_hash` (`:53-60`). (Their replacements land in
Tasks 2 and 5: append-not-rotate above, revoked_at in resolve.) `test_plaintext_token_is_never_stored`
and `test_mint_scopes_writes_to_the_named_installation` break too — rewrite them in Task 6
when `tenancy.mint` is deleted; for now mark both with
`@pytest.mark.skip(reason="single-column model retired mid-plan; rewritten in Task 6")`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && python -m pytest tests/test_store.py -k "installation_token or migration_6" -v`
Expected: FAIL — `AttributeError: module 'doug.store' has no attribute 'insert_installation_token'`

- [ ] **Step 3: Implement**

In `api/doug/store.py`:

(a) Delete the `token_hash` column and its comment from the `installations` Table (`store.py:183-186`).

(b) After the `installation_repos` Table, add:

```python
# Tenant API keys (spec 2026-08-04). Multiple keys per installation; each
# frozen to a repo selection at mint and intersected against the LIVE ledger
# at resolve — installations.state and installation_repos.state are the
# authority, these rows are the claim. Repo ids only: full_name is display
# everywhere (the MT4 lesson, baked into the schema).
installation_tokens = Table(
    "installation_tokens",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("installation_id", BigInteger, nullable=False, index=True),
    # Plaintext on purpose: the lookup is a key ID, not a secret — O(1)
    # btree resolve, safe in logs and list output. The SECRET is what
    # token_hash covers, and it is never stored in any form but the HMAC.
    Column("token_lookup", String(8), nullable=False, unique=True),
    Column("token_hash", Text, nullable=False),
    Column("hash_version", Integer, nullable=False, server_default="1"),
    Column("last4", String(4), nullable=False),
    Column("label", String(100)),
    Column("repo_selection", String(10), nullable=False),  # all | selected
    Column("scopes", JSON, nullable=False),
    Column("minted_by", String(200), nullable=False),  # audit only, never authority
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True)),  # NULL = durable
    Column("revoked_at", DateTime(timezone=True)),  # soft revoke; rows never deleted
    Column("last_used_at", DateTime(timezone=True)),
)

installation_token_repos = Table(
    "installation_token_repos",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("token_id", Integer, nullable=False, index=True),
    Column("github_repo_id", BigInteger, nullable=False),
    UniqueConstraint("token_id", "github_repo_id", name="uq_installation_token_repo"),
)
```

(c) Accessors (after `active_repos`). `_utc(dt)` is the tz normalizer used by
several of them:

```python
def _utc(dt):
    """sqlite hands back naive datetimes for DateTime(timezone=True) columns;
    every stored value is UTC, so naive means 'UTC, badly labelled'."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def insert_installation_token(
    installation_id: int,
    *,
    token_lookup: str,
    token_hash: str,
    hash_version: int,
    last4: str,
    label: str | None,
    repo_selection: str,
    scopes: list[str],
    minted_by: str,
    expires_at: datetime | None,
) -> int | None:
    """A new key row, appended — NEVER an update of an existing one. Returns
    None when storage is off or the installation has no row (no row means
    Doug was never installed there; the absence is a refusal)."""
    engine = _get_engine()
    if engine is None:
        return None
    with engine.begin() as conn:
        known = conn.execute(
            select(installations.c.id).where(
                installations.c.installation_id == installation_id
            )
        ).scalar_one_or_none()
        if known is None:
            return None
        return conn.execute(
            installation_tokens.insert().returning(installation_tokens.c.id),
            {
                "installation_id": installation_id,
                "token_lookup": token_lookup,
                "token_hash": token_hash,
                "hash_version": hash_version,
                "last4": last4,
                "label": label,
                "repo_selection": repo_selection,
                "scopes": scopes,
                "minted_by": minted_by,
                "created_at": datetime.now(UTC),
                "expires_at": expires_at,
            },
        ).scalar_one()


def set_installation_token_repos(token_id: int, repo_ids: list[int]) -> None:
    engine = _get_engine()
    if engine is None or not repo_ids:
        return
    with engine.begin() as conn:
        conn.execute(
            installation_token_repos.insert(),
            [{"token_id": token_id, "github_repo_id": rid} for rid in repo_ids],
        )


def installation_token_by_lookup(token_lookup: str) -> dict | None:
    """The key row plus the LIVE installation state, in one query. The JOIN
    (not a LEFT JOIN) makes a key whose installation row is missing resolve
    to nothing — fail closed, same direction as everything else here."""
    engine = _get_engine()
    if engine is None:
        return None
    with engine.connect() as conn:
        row = (
            conn.execute(
                select(
                    installation_tokens,
                    installations.c.state.label("installation_state"),
                )
                .join(
                    installations,
                    installations.c.installation_id
                    == installation_tokens.c.installation_id,
                )
                .where(installation_tokens.c.token_lookup == token_lookup)
            )
            .mappings()
            .first()
        )
    if row is None:
        return None
    out = dict(row)
    out["expires_at"] = _utc(out["expires_at"])
    out["revoked_at"] = _utc(out["revoked_at"])
    out["last_used_at"] = _utc(out["last_used_at"])
    return out


def installation_token_repo_ids(token_id: int) -> set[int]:
    engine = _get_engine()
    if engine is None:
        return set()
    with engine.connect() as conn:
        return {
            int(r.github_repo_id)
            for r in conn.execute(
                select(installation_token_repos.c.github_repo_id).where(
                    installation_token_repos.c.token_id == token_id
                )
            )
        }


def count_installation_tokens_minted_since(
    installation_id: int, since: datetime
) -> int | None:
    """None on ANY failure, including storage-off. The daily mint cap is
    fail-open by spec: a counting error must log-and-allow at the caller,
    never refuse a legitimate mint because a SELECT hiccuped."""
    engine = _get_engine()
    if engine is None:
        return None
    try:
        from sqlalchemy import func

        with engine.connect() as conn:
            return int(
                conn.execute(
                    select(func.count())
                    .select_from(installation_tokens)
                    .where(
                        (installation_tokens.c.installation_id == installation_id)
                        & (installation_tokens.c.created_at >= since)
                    )
                ).scalar_one()
            )
    except Exception:  # noqa: BLE001 — fail-open is the contract
        return None


def touch_installation_token_last_used(token_id: int) -> None:
    """Best-effort convenience timestamp, throttled to one write per key per
    60s. Deliberately NOT part of the resolve contract: a failure here must
    never fail a request, and the throttle keeps the hot path from writing
    on every call."""
    engine = _get_engine()
    if engine is None:
        return
    try:
        now = datetime.now(UTC)
        with engine.begin() as conn:
            conn.execute(
                update(installation_tokens)
                .where(
                    (installation_tokens.c.id == token_id)
                    & (
                        (installation_tokens.c.last_used_at.is_(None))
                        | (installation_tokens.c.last_used_at < now - timedelta(seconds=60))
                    )
                )
                .values(last_used_at=now)
            )
    except Exception:  # noqa: BLE001 — convenience, not audit
        pass
```

Add `timedelta` to the existing `datetime` import at the top of `store.py`.

(d) In `api/doug/migrations.py` — append migration 6 and extend `_SATISFIED`:

```python
    (
        6,
        (
            # Tenant API keys (spec 2026-08-04): the single-column credential
            # moves to the installation_tokens table (a NEW table, so
            # create_all owns it — no DDL for it here). The only change an
            # EXISTING table needs is dropping the retired column. No data
            # migrates: no dispensed token exists in any environment (MT0
            # meant prod dispense 404'd from the day it shipped).
            #
            # On a fresh database create_all() has already built
            # installations WITHOUT token_hash, so this DROP finds its work
            # done and lands in _SATISFIED's third marker below. The table
            # itself always exists by the time apply() runs (create_all made
            # it), so this is never the ALTER-on-missing-TABLE crash-loop
            # PR #48 reverted.
            "ALTER TABLE installations DROP COLUMN token_hash",
        ),
    ),
```

```python
# "no such column" is sqlite's voice for a DROP COLUMN whose work is already
# done; "does not exist" is Postgres's. Both only ever reach _run from a
# statement in MIGRATIONS, so the blast radius of the broad Postgres string
# is our own migration list, not arbitrary DDL.
_SATISFIED = ("duplicate column name", "already exists", "no such column", "does not exist")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && python -m pytest tests/test_store.py tests/test_tenancy.py tests/test_keyformat.py -q`
Expected: new tests pass; two old tenancy tests deleted, two skipped; everything else green.

- [ ] **Step 5: Full-suite check and commit**

Run: `cd api && python -m pytest tests/ -q` — anything else touching `token_hash` will surface here (grep first: `grep -rn "token_hash" api/ --include="*.py"` should show only `installation_tokens.c.token_hash` uses).
Expected: green except the two deliberate skips.

```bash
git add api/doug/store.py api/doug/migrations.py api/tests/test_store.py api/tests/test_tenancy.py
git commit -m "feat: installation_tokens schema, accessors, migration 6"
```

### Task 3: Pepper config and hashing in `tenancy.py`

**Files:**
- Modify: `api/doug/tenancy.py` (add below the imports; add `import base64`, `import binascii`, `import hmac`, `import os` — `hashlib`/`secrets` already imported)
- Test: `api/tests/test_tenancy.py` (append)

**Interfaces:**
- Consumes: env vars `DOUG_TOKEN_PEPPER`, `DOUG_TOKEN_PEPPER_V<n>`.
- Produces: `class KeysNotConfigured(Exception)`, `_pepper(version: int) -> bytes | None`, `_current_hash_version() -> int`, `hash_secret(secret: str, version: int) -> str | None`, `keys_configured() -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
# append to api/tests/test_tenancy.py
import base64

PEPPER_B64 = base64.b64encode(b"p" * 32).decode()
PEPPER2_B64 = base64.b64encode(b"q" * 32).decode()


def _pepper_env(monkeypatch, **extra):
    monkeypatch.setenv("DOUG_TOKEN_PEPPER", PEPPER_B64)
    for name, val in extra.items():
        monkeypatch.setenv(name, val)


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && python -m pytest tests/test_tenancy.py -k "pepper or hash_version or hash_secret" -v`
Expected: FAIL — `AttributeError: module 'doug.tenancy' has no attribute 'hash_secret'`

- [ ] **Step 3: Implement**

```python
# api/doug/tenancy.py, below the TOKEN_PREFIX block
class KeysNotConfigured(Exception):
    """Raised by mint/resolve when no valid pepper is configured. The API
    layer renders it as 503: minting a key we could never verify (or
    silently failing every verify) would be the config drift lema's
    APIKeysConfigured() gate exists to prevent."""


def _pepper(version: int) -> bytes | None:
    """The HMAC pepper for a hash_version, or None. Peppers are why a
    DB-only breach yields unusable hashes: key hashes are effectively
    unsalted (the row is found by lookup, not by hash), so the secret
    ingredient has to live OUTSIDE the database."""
    name = "DOUG_TOKEN_PEPPER" if version == 1 else f"DOUG_TOKEN_PEPPER_V{version}"
    raw = os.environ.get(name)
    if not raw:
        return None
    try:
        decoded = base64.b64decode(raw, validate=True)
    except (ValueError, binascii.Error):
        return None
    return decoded if len(decoded) == 32 else None


def _current_hash_version() -> int:
    """Highest configured pepper version — what NEW mints use. Old keys keep
    verifying under their recorded version, which is what makes pepper
    rotation rolling instead of lema's accepted flag-day."""
    v = 1
    while _pepper(v + 1) is not None:
        v += 1
    return v


def hash_secret(secret: str, version: int) -> str | None:
    """Peppered HMAC-SHA256, hex. None when that version has no pepper —
    an unknown version fails closed rather than guessing."""
    pepper = _pepper(version)
    if pepper is None:
        return None
    return hmac.new(pepper, secret.encode(), hashlib.sha256).hexdigest()


def keys_configured() -> bool:
    return _pepper(_current_hash_version()) is not None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && python -m pytest tests/test_tenancy.py -q`
Expected: PASS (with the two Task-2 skips)

- [ ] **Step 5: Commit**

```bash
git add api/doug/tenancy.py api/tests/test_tenancy.py
git commit -m "feat: versioned token pepper — rolling rotation, fail-closed on unknown versions"
```

### Task 4: Mint proofs — `verify_org_admin`, `verify_repos_admin`, `mint_key`

**Files:**
- Modify: `api/doug/tenancy.py`
- Test: `api/tests/test_tenancy.py` (append)

**Interfaces:**
- Consumes: `keyformat.generate()`, `store.insert_installation_token`, `store.set_installation_token_repos`, `hash_secret`, `_current_hash_version`, existing `verify_admin`, `_caller_client`, `app_auth`.
- Produces:
  - `caller_login(pat: str) -> str | None` — `GET /user` on the caller's quota.
  - `verify_org_admin(pat: str, owner: str) -> int | None` — proof for `selection=all`; returns installation id.
  - `verify_repos_admin(pat: str, repos: list[tuple[str, str]]) -> int | None` — proof for `selection=selected`; all repos must prove to the SAME installation.
  - `MintedKey(NamedTuple: token, token_id, last4, expires_at)`.
  - `mint_key(installation_id: int, *, repo_selection: str, repo_ids: list[int], label: str | None, expires_in_days: int, minted_by: str) -> MintedKey | None` — raises `KeysNotConfigured` when no pepper.

githubkit method names to confirm at implementation time (tests stub them, so
confirm against the installed githubkit before wiring the real calls):
`rest.users.get_authenticated()`, `rest.orgs.get_membership_for_authenticated_user(org=...)`,
`rest.apps.get_org_installation(org=...)`, `rest.apps.get_user_installation(username=...)`.

- [ ] **Step 1: Write the failing tests**

```python
# append to api/tests/test_tenancy.py
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
    import pytest
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && python -m pytest tests/test_tenancy.py -k "org_admin or repos_proof or mint_key or stranger or user_install" -v`
Expected: FAIL — `AttributeError: ... no attribute 'verify_org_admin'`

- [ ] **Step 3: Implement**

```python
# api/doug/tenancy.py
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

from . import keyformat  # add to the existing relative import line


class MintedKey(NamedTuple):
    token: str
    token_id: int
    last4: str
    expires_at: datetime | None


def caller_login(pat: str) -> str | None:
    """GET /user on the caller's own quota. Used for minted_by attribution
    and as the cheap first hop of the User-install proof."""
    try:
        me = _caller_client(pat).rest.users.get_authenticated()
    except Exception as e:  # noqa: BLE001 — an unusable PAT proves nothing
        print(
            f"doug: dispense denied at the identity check "
            f"({type(e).__name__}: {str(e)[:200]})",
            file=sys.stderr,
        )
        return None
    login = getattr(me.parsed_data, "login", None)
    return login if isinstance(login, str) and login else None


def verify_org_admin(pat: str, owner: str) -> int | None:
    """Prove the caller may hold an installation-wide key for `owner`.

    Same load-bearing order as verify_admin: every PAT call (identity,
    membership) runs before the app-JWT installation lookup, so a caller
    who proves nothing spends only their own quota.

    Two ways to prove it, tried cheapest-first:
    - the caller IS the account (User-type install): login match,
      case-insensitive because GitHub logins are;
    - the caller holds an ACTIVE admin membership in the org.
    """
    login = caller_login(pat)
    if login is None:
        return None
    is_owner = login.lower() == owner.lower()
    if not is_owner:
        try:
            membership = _caller_client(pat).rest.orgs.get_membership_for_authenticated_user(
                org=owner
            )
        except Exception as e:  # noqa: BLE001 — not a member, or org missing
            print(
                f"doug: dispense denied org-admin {owner} at the membership check "
                f"({type(e).__name__}: {str(e)[:200]})",
                file=sys.stderr,
            )
            return None
        data = membership.parsed_data
        if getattr(data, "role", None) != "admin" or getattr(data, "state", None) != "active":
            return None

    if not app_auth.enabled():
        return None
    try:
        if is_owner:
            found = app_auth.app_client().rest.apps.get_user_installation(username=owner)
        else:
            found = app_auth.app_client().rest.apps.get_org_installation(org=owner)
    except Exception as e:  # noqa: BLE001 — 404 = Doug is not installed there
        print(
            f"doug: dispense denied org-admin {owner} at the installation lookup "
            f"({type(e).__name__}: {str(e)[:200]})",
            file=sys.stderr,
        )
        return None
    installation_id = getattr(found.parsed_data, "id", None)
    return installation_id if isinstance(installation_id, int) else None


def verify_repos_admin(pat: str, repos: list[tuple[str, str]]) -> int | None:
    """Prove admin on EVERY named repo, and that all of them live under one
    installation. A mixed-owner list cannot be one installation's, so it is
    refused before any call spends any quota at all."""
    if not repos:
        return None
    owners = {owner.lower() for owner, _ in repos}
    if len(owners) != 1:
        return None
    installation_ids = set()
    for owner, name in repos:
        installation_id = verify_admin(pat, owner, name)
        if installation_id is None:
            return None
        installation_ids.add(installation_id)
    if len(installation_ids) != 1:
        return None
    return installation_ids.pop()


def mint_key(
    installation_id: int,
    *,
    repo_selection: str,
    repo_ids: list[int],
    label: str | None,
    expires_in_days: int,
    minted_by: str,
) -> MintedKey | None:
    """Append a new key. Returns the plaintext exactly once, or None when
    storage is off / the installation is unknown. Raises KeysNotConfigured
    with no pepper — we never mint what we cannot verify."""
    if not keys_configured():
        raise KeysNotConfigured()
    version = _current_hash_version()
    minted = keyformat.generate()
    expires_at = (
        datetime.now(UTC) + timedelta(days=expires_in_days) if expires_in_days else None
    )
    token_id = store.insert_installation_token(
        installation_id,
        token_lookup=minted.lookup,
        token_hash=hash_secret(minted.secret, version),
        hash_version=version,
        last4=minted.last4,
        label=label,
        repo_selection=repo_selection,
        scopes=["queue:read"],
        minted_by=minted_by,
        expires_at=expires_at,
    )
    if token_id is None:
        return None
    if repo_selection == "selected":
        store.set_installation_token_repos(token_id, repo_ids)
    return MintedKey(
        token=minted.token, token_id=token_id, last4=minted.last4, expires_at=expires_at
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && python -m pytest tests/test_tenancy.py -q`
Expected: PASS (two Task-2 skips remain)

- [ ] **Step 5: Commit**

```bash
git add api/doug/tenancy.py api/tests/test_tenancy.py
git commit -m "feat: selection-covering mint proofs and append-only mint_key"
```

### Task 5: `resolve` returns a live-intersected `TokenContext`

**Files:**
- Modify: `api/doug/tenancy.py` (replace `resolve`, `tenancy.py:55-76`)
- Modify: `api/doug/api.py` (`queue` `:484`, one line: `installation_id = ctx.installation_id`; `_operator_only` `:457` gains the 503 catch)
- Test: `api/tests/test_tenancy.py`

**Interfaces:**
- Consumes: `keyformat.parse`, `store.installation_token_by_lookup`, `store.installation_token_repo_ids`, `store.active_repos`, `hash_secret`, `keys_configured`.
- Produces: `@dataclass(frozen=True) TokenContext(installation_id: int, token_id: int, scopes: tuple[str, ...], repo_ids: frozenset[int] | None)`; `resolve(token: str) -> TokenContext | None` (raises `KeysNotConfigured` only for key-shaped tokens when no pepper is set). `repo_ids is None` means selection `all` — filter by installation only.

- [ ] **Step 1: Write the failing tests**

```python
# append to api/tests/test_tenancy.py
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
    import pytest
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && python -m pytest tests/test_tenancy.py -k "resolve or uninstall or intersects" -v`
Expected: FAIL — old `resolve` returns `int | None`, no `TokenContext` attributes.

- [ ] **Step 3: Implement**

Replace `resolve` (`tenancy.py:55-76`) — the old body goes away entirely:

```python
from dataclasses import dataclass

_DUMMY_SECRET = "0" * keyformat.SECRET_LEN


@dataclass(frozen=True)
class TokenContext:
    """What a resolved key may see. repo_ids is None for selection='all'
    (installation-wide: filter rows by installation_id only) and a non-empty
    frozenset for 'selected' — never empty, because an empty live
    intersection fails resolve instead of returning a context."""

    installation_id: int
    token_id: int
    scopes: tuple[str, ...]
    repo_ids: frozenset[int] | None


def resolve(token: str) -> TokenContext | None:
    """Map a presented token to its live context, or None.

    Chain runs cheapest-first: offline parse+CRC (zero I/O), one indexed
    SELECT, one HMAC, then the liveness checks. Every failure is the same
    None — the route's uniform 401 leaks nothing about WHICH check failed.
    The stored hash is compared via compare_digest, and a lookup miss burns
    a dummy HMAC so a miss and a wrong secret cost the same clock.

    The key's stored selection is a claim; installations.state and
    installation_repos.state are the authority, read LIVE on every call.
    That intersection is Doug's analog of lema's live-role re-derivation:
    uninstall/suspend end access next request (MT2), and a 'selected' key
    sheds any repo the installation no longer covers.
    """
    parsed = keyformat.parse(token)
    if parsed is None:
        return None
    if not keys_configured():
        raise KeysNotConfigured()
    row = store.installation_token_by_lookup(parsed.lookup)
    if row is None:
        hash_secret(_DUMMY_SECRET, _current_hash_version())
        return None
    expected = row["token_hash"]
    computed = hash_secret(parsed.secret, row["hash_version"])
    if computed is None or not hmac.compare_digest(computed, expected):
        return None
    if row["revoked_at"] is not None:
        return None
    if row["expires_at"] is not None and row["expires_at"] <= datetime.now(UTC):
        return None
    if row["installation_state"] != "active":
        return None
    repo_ids: frozenset[int] | None = None
    if row["repo_selection"] == "selected":
        frozen = store.installation_token_repo_ids(row["id"])
        live = {rid for rid, _ in store.active_repos(row["installation_id"])}
        effective = frozen & live
        if not effective:
            return None
        repo_ids = frozenset(effective)
    store.touch_installation_token_last_used(row["id"])
    return TokenContext(
        installation_id=int(row["installation_id"]),
        token_id=int(row["id"]),
        scopes=tuple(row["scopes"] or ()),
        repo_ids=repo_ids,
    )
```

In `api/doug/api.py` — keep the routes compiling against the new return type
(full queue rework is Task 6):

- `queue` (`api.py:483-486`) becomes:

```python
    ctx: tenancy.TokenContext | None = None
    if not hmac.compare_digest(x_doug_token, expected):
        try:
            ctx = tenancy.resolve(x_doug_token)
        except tenancy.KeysNotConfigured:
            raise HTTPException(status_code=503, detail="token verification not configured")
        if ctx is None:
            raise HTTPException(status_code=401, detail="bad token")
    installation_id = ctx.installation_id if ctx is not None else None
```

- `_operator_only` (`api.py:457`) becomes:

```python
    try:
        if tenancy.resolve(x_doug_token) is not None:
            raise HTTPException(status_code=404, detail="not found")
    except tenancy.KeysNotConfigured:
        raise HTTPException(status_code=503, detail="token verification not configured")
    raise HTTPException(status_code=401, detail="bad token")
```

- [ ] **Step 4: Run the whole suite**

Run: `cd api && python -m pytest tests/ -q`
Expected: tenancy/store/keyformat green. Any `test_api.py` dispense/queue tests
that minted via the OLD single-column path will fail here — that is Task 6's
work; if any fail for that reason only, mark them
`@pytest.mark.skip(reason="rewritten in Task 6")` in this commit and note it in
the commit body (never leave them silently red).

- [ ] **Step 5: Commit**

```bash
git add api/doug/tenancy.py api/doug/api.py api/tests/test_tenancy.py api/tests/test_api.py
git commit -m "feat: resolve returns a live-intersected TokenContext (MT2 closes structurally)"
```

### Task 6: The endpoints — mint body/proofs/cap, queue repo filter, legacy retirement

**Files:**
- Modify: `api/doug/api.py` (`TokenRequest`/`TokenResponse`/`dispense_token` `:555-598`; `queue` `:462-552`)
- Modify: `api/doug/tenancy.py` (DELETE old `mint` `:32-52`, `_hash` `:28-29`, `TOKEN_PREFIX` `:25`; module docstring paragraph about sha256 updated to name the peppered scheme)
- Modify: `api/doug/store.py` (`latest_reviews` gains `repo_ids` param, `:1176-1218`)
- Test: `api/tests/test_api.py`, `api/tests/test_store.py`, `api/tests/test_tenancy.py`

**Interfaces:**
- Consumes: everything Tasks 1–5 produced.
- Produces:
  - `TokenRequest(BaseModel)`: `selection: str | None`, `owner: str | None`, `repos: list[str] | None`, `repo: str | None` (legacy), `label: str | None`, `expires_in_days: int = 0`.
  - `TokenResponse(BaseModel)`: `token: str`, `token_id: int`, `installation_id: int`, `selection: str`, `repos: list[str]`, `last4: str`, `expires_at: datetime | None`.
  - `store.latest_reviews(limit=200, repo=None, installation_id=None, repo_ids: set[int] | None = None)` — `repo_ids` ANDs `verdicts.github_repo_id.in_(repo_ids)` INSIDE the grouped subquery.
  - Constants in `api.py`: `MAX_REPOS_PER_MINT = 20`, `MAX_MINTS_PER_DAY = 30`.

- [ ] **Step 1: Write the failing tests**

Rework the dispense tests in `api/tests/test_api.py` (`:1778-1860` area) — the
existing `_db`-style fixtures and `client` are already there; follow the file's
conventions. Un-skip and rewrite the two tests skipped in Task 2, and delete any
Task-5 skips this task rewrites. New/updated tests:

```python
def _pepper_env(monkeypatch):
    import base64
    monkeypatch.setenv("DOUG_TOKEN_PEPPER", base64.b64encode(b"p" * 32).decode())


def test_dispense_selected_returns_a_key_scoped_to_the_named_repos(tmp_path, monkeypatch):
    _api_db(tmp_path, monkeypatch)  # whatever test_api.py's ledger fixture is named
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
    first = client.post("/v1/installations/token", json=body, headers={"X-GitHub-Token": "t"}).json()
    second = client.post("/v1/installations/token", json=body, headers={"X-GitHub-Token": "t"}).json()
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
    # Over the cap → 404 (uniform).
    monkeypatch.setattr(store, "count_installation_tokens_minted_since", lambda i, s: 30)
    assert client.post("/v1/installations/token", json=body, headers={"X-GitHub-Token": "t"}).status_code == 404
    # Counter broken → None → allow (fail-open by spec).
    monkeypatch.setattr(store, "count_installation_tokens_minted_since", lambda i, s: None)
    assert client.post("/v1/installations/token", json=body, headers={"X-GitHub-Token": "t"}).status_code == 200


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
        assert client.post("/v1/installations/token", json=bad, headers=headers).status_code == 404, bad


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
    repos_seen = {item["pr"]["repo"] for item in r.json()["items"]}
    assert repos_seen == {"drewjst/a"}
```

`_seed_verdict` = whatever helper `test_api.py` already uses to write a verdict
row with `pr_meta` (grep for the existing tenant-queue test around `:1948` and
reuse its seeding verbatim; if it is inline, extract it into a helper as part
of this task).

And in `api/tests/test_store.py`:

```python
def test_latest_reviews_repo_ids_filter_is_inside_the_grouped_subquery(tmp_path, monkeypatch):
    """A CI row or sibling-repo row must not win max(id) and then vanish —
    same reasoning as the installation filter (store.py:1192-1196)."""
    _db(tmp_path, monkeypatch)
    # Two verdicts, same installation, different repos:
    _write_verdict(repo="drewjst/a", github_repo_id=111, installation_id=150424894, pr_number=1)
    _write_verdict(repo="drewjst/b", github_repo_id=222, installation_id=150424894, pr_number=2)
    rows = store.latest_reviews(installation_id=150424894, repo_ids={111})
    assert {r["repo"] for r in rows} == {"drewjst/a"}
```

(`_write_verdict` = test_store.py's existing verdict-seeding helper; reuse it.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && python -m pytest tests/test_api.py -k "dispense or queue_selected" tests/test_store.py -k repo_ids -v`
Expected: FAIL — old `TokenRequest` requires `repo`, endpoint calls deleted-in-this-task `tenancy.mint`.

- [ ] **Step 3: Implement**

(a) `store.latest_reviews` — new keyword `repo_ids: set[int] | None = None`; inside the existing scoped filter block (`store.py:1197-1199`):

```python
    scoped = verdicts.c.tier != EXTERNAL_TIER
    if installation_id is not None:
        scoped = scoped & (verdicts.c.installation_id == installation_id)
    if repo_ids is not None:
        # Same placement rule as the tenant filter above: INSIDE the grouped
        # subquery, or an out-of-selection row wins max(id) and its PR
        # disappears instead of falling back.
        scoped = scoped & (verdicts.c.github_repo_id.in_(repo_ids))
```

(b) `api.py` — replace `TokenRequest`/`TokenResponse`/`dispense_token` (`:555-598`):

```python
MAX_REPOS_PER_MINT = 20   # bounds PAT-side GitHub calls per request
MAX_MINTS_PER_DAY = 30    # per installation per UTC day; fail-open


class TokenRequest(BaseModel):
    selection: str | None = None          # "all" | "selected"
    owner: str | None = None              # required for selection="all"
    repos: list[str] | None = None        # required for selection="selected"
    repo: str | None = None               # legacy PR #48 body — one selected repo
    label: str | None = None
    expires_in_days: int = 0


class TokenResponse(BaseModel):
    token: str
    token_id: int
    installation_id: int
    selection: str
    repos: list[str]
    last4: str
    expires_at: datetime | None


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="not found")


@app.post("/v1/installations/token")
def dispense_token(body: TokenRequest, x_github_token: str = Header("")) -> TokenResponse:
    """Mint a tenant API key, proving authority through GitHub.

    Deliberately public: the proof is the caller's own GitHub credential.
    PROOF MUST COVER THE SELECTION — org-admin (or the account owner, for a
    User install) for selection='all'; admin on EVERY named repo for
    selection='selected'. Every verification or validation failure is the
    same 404: a caller can never distinguish "exists but refused" from
    "does not exist".

    Mint APPENDS — it never rotates another key, so this endpoint is no
    longer a denial-of-service against the tenant's own integration (MT5).
    """
    if not x_github_token:
        raise HTTPException(status_code=401, detail="X-GitHub-Token required")
    if not store.enabled():
        raise HTTPException(status_code=503, detail="no ledger configured")

    # Normalize the legacy body before validating anything else.
    selection, repos, owner = body.selection, body.repos, body.owner
    if selection is None and body.repo is not None:
        selection, repos = "selected", [body.repo]

    if not (0 <= body.expires_in_days <= 366):
        raise _not_found()
    if body.label is not None and len(body.label) > 100:
        raise _not_found()

    if selection == "selected":
        if not repos or len(repos) > MAX_REPOS_PER_MINT:
            raise _not_found()
        parsed_repos: list[tuple[str, str]] = []
        for full in repos:
            repo_owner, _, name = full.partition("/")
            if not repo_owner or not name or "/" in name:
                raise _not_found()
            parsed_repos.append((repo_owner, name))
        installation_id = tenancy.verify_repos_admin(x_github_token, parsed_repos)
    elif selection == "all":
        if not owner or "/" in owner:
            raise _not_found()
        installation_id = tenancy.verify_org_admin(x_github_token, owner)
    else:
        raise _not_found()
    if installation_id is None:
        raise _not_found()

    midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    minted_today = store.count_installation_tokens_minted_since(installation_id, midnight)
    if minted_today is not None and minted_today >= MAX_MINTS_PER_DAY:
        # None means "could not count" and ALLOWS — the cap is fail-open.
        raise _not_found()

    minted_by = tenancy.caller_login(x_github_token)
    if minted_by is None:
        raise _not_found()

    repo_ids: list[int] = []
    if selection == "selected":
        by_name = {full_name: rid for rid, full_name in store.active_repos(installation_id)}
        # The ledger may lag GitHub (MT0 taught how badly); GitHub already
        # proved these repos belong to this installation, so a name the
        # ledger has not heard of yet refuses the mint rather than minting
        # a key whose junction rows point at nothing.
        try:
            repo_ids = [by_name[full] for full in repos]
        except KeyError:
            raise _not_found()

    try:
        minted = tenancy.mint_key(
            installation_id,
            repo_selection=selection,
            repo_ids=repo_ids,
            label=body.label,
            expires_in_days=body.expires_in_days,
            minted_by=minted_by,
        )
    except tenancy.KeysNotConfigured:
        raise HTTPException(status_code=503, detail="token minting not configured")
    if minted is None:
        raise _not_found()
    # The token rides in the response ONCE. This log line is the only other
    # trace of the mint and carries the id, never the credential.
    print(
        f"doug: minted key id={minted.token_id} installation={installation_id} "
        f"selection={selection} last4={minted.last4} by={minted_by}",
        file=sys.stderr,
    )
    return TokenResponse(
        token=minted.token,
        token_id=minted.token_id,
        installation_id=installation_id,
        selection=selection,
        repos=repos if selection == "selected" else [],
        last4=minted.last4,
        expires_at=minted.expires_at,
    )
```

Add `from datetime import UTC, datetime` to `api.py`'s imports if not present.

(c) `queue` — thread `ctx.repo_ids` through (building on Task 5's swap):

```python
        items = [...  # unchanged item construction
            for row in store.latest_reviews(
                repo=repo,
                installation_id=installation_id,
                repo_ids=ctx.repo_ids if ctx is not None else None,
            )
            if row["pr_meta"]
        ]
```

(d) `tenancy.py` — delete `mint` (`:32-52`), `_hash` (`:28-29`), `TOKEN_PREFIX`
(`:23-25`); update the module docstring's sha256 paragraph to describe the
peppered-HMAC scheme and keyformat. Grep check before committing:
`grep -rn "TOKEN_PREFIX\|tenancy.mint(" api/ --include="*.py"` → only
`mint_key` call sites remain.

(e) Rewrite the two Task-2-skipped tenancy tests against the new stack
(plaintext-never-stored is Task 4's `test_mint_key_stores_only_the_peppered_hash`
— delete the skipped original; mint-scopes-writes rewrites as: two
installations, one `mint_key` each, each key resolves to its own installation).

- [ ] **Step 4: Run the whole suite**

Run: `cd api && python -m pytest tests/ -q`
Expected: fully green, zero skips left from Tasks 2/5.

- [ ] **Step 5: Commit**

```bash
git add api/doug/api.py api/doug/tenancy.py api/doug/store.py api/tests/
git commit -m "feat: selection-scoped dispense + repo-filtered queue; retire single-column tokens (MT1, MT5)"
```

---

## Slice B — lifecycle: list, revoke, uninstall bulk-revoke

### Task 7: Store lifecycle helpers

**Files:**
- Modify: `api/doug/store.py`
- Test: `api/tests/test_store.py`

**Interfaces:**
- Produces:
  - `list_installation_tokens(installation_id: int) -> list[dict]` — every column EXCEPT `token_hash`, newest first, revoked rows included (they are audit history).
  - `revoke_installation_token(token_id: int, installation_id: int) -> bool` — soft, idempotent (`COALESCE`), ownership inside the WHERE; True iff a row matched.
  - `revoke_all_installation_tokens(installation_id: int) -> int` — rows newly revoked.

- [ ] **Step 1: Write the failing tests**

```python
def test_list_tokens_masks_the_hash_and_orders_newest_first(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    _seed_install()
    kw = dict(
        token_hash="ab" * 32, hash_version=1, last4="wxyz", label=None,
        repo_selection="all", scopes=["queue:read"], minted_by="drewjst",
        expires_at=None,
    )
    a = store.insert_installation_token(150424894, token_lookup="AAAAAAAA", **kw)
    b = store.insert_installation_token(150424894, token_lookup="BBBBBBBB", **kw)
    rows = store.list_installation_tokens(150424894)
    assert [r["id"] for r in rows] == [b, a]
    assert all("token_hash" not in r for r in rows)


def test_revoke_is_ownership_scoped_and_idempotent(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    _seed_install(150424894)
    _seed_install(999999999)
    kw = dict(
        token_hash="ab" * 32, hash_version=1, last4="wxyz", label=None,
        repo_selection="all", scopes=["queue:read"], minted_by="drewjst",
        expires_at=None,
    )
    token_id = store.insert_installation_token(150424894, token_lookup="AAAAAAAA", **kw)
    # Foreign installation id in the WHERE → no match, indistinguishable from absent.
    assert store.revoke_installation_token(token_id, 999999999) is False
    assert store.installation_token_by_lookup("AAAAAAAA")["revoked_at"] is None
    assert store.revoke_installation_token(token_id, 150424894) is True
    first_stamp = store.installation_token_by_lookup("AAAAAAAA")["revoked_at"]
    assert store.revoke_installation_token(token_id, 150424894) is True  # idempotent
    assert store.installation_token_by_lookup("AAAAAAAA")["revoked_at"] == first_stamp


def test_revoke_all_stamps_only_live_keys(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    _seed_install()
    kw = dict(
        token_hash="ab" * 32, hash_version=1, last4="wxyz", label=None,
        repo_selection="all", scopes=["queue:read"], minted_by="drewjst",
        expires_at=None,
    )
    a = store.insert_installation_token(150424894, token_lookup="AAAAAAAA", **kw)
    store.insert_installation_token(150424894, token_lookup="BBBBBBBB", **kw)
    store.revoke_installation_token(a, 150424894)
    stamp_a = store.installation_token_by_lookup("AAAAAAAA")["revoked_at"]
    assert store.revoke_all_installation_tokens(150424894) == 1  # only B was live
    assert store.installation_token_by_lookup("AAAAAAAA")["revoked_at"] == stamp_a
    assert store.installation_token_by_lookup("BBBBBBBB")["revoked_at"] is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && python -m pytest tests/test_store.py -k "revoke or list_tokens" -v`
Expected: FAIL — `AttributeError`

- [ ] **Step 3: Implement**

```python
def list_installation_tokens(installation_id: int) -> list[dict]:
    """Masked list for the management endpoint: everything but the hash.
    Revoked rows stay listed — they are the audit trail, and 'when did that
    key die' is a question this table exists to answer."""
    engine = _get_engine()
    if engine is None:
        return []
    cols = [c for c in installation_tokens.c if c.name != "token_hash"]
    with engine.connect() as conn:
        rows = conn.execute(
            select(*cols)
            .where(installation_tokens.c.installation_id == installation_id)
            .order_by(installation_tokens.c.id.desc())
        ).mappings().all()
    out = []
    for row in rows:
        d = dict(row)
        for key in ("expires_at", "revoked_at", "last_used_at", "created_at"):
            d[key] = _utc(d[key])
        out.append(d)
    return out


def revoke_installation_token(token_id: int, installation_id: int) -> bool:
    """Soft revoke, idempotent, ownership INSIDE the where: a foreign
    token_id matches nothing and is indistinguishable from a missing one."""
    engine = _get_engine()
    if engine is None:
        return False
    with engine.begin() as conn:
        result = conn.execute(
            update(installation_tokens)
            .where(
                (installation_tokens.c.id == token_id)
                & (installation_tokens.c.installation_id == installation_id)
            )
            .values(revoked_at=func.coalesce(installation_tokens.c.revoked_at, datetime.now(UTC)))
        )
    return result.rowcount > 0


def revoke_all_installation_tokens(installation_id: int) -> int:
    """The uninstall webhook's bulk stamp. Belt-and-braces on top of
    resolve's live state check — the audit trail is the point."""
    engine = _get_engine()
    if engine is None:
        return 0
    with engine.begin() as conn:
        result = conn.execute(
            update(installation_tokens)
            .where(
                (installation_tokens.c.installation_id == installation_id)
                & (installation_tokens.c.revoked_at.is_(None))
            )
            .values(revoked_at=datetime.now(UTC))
        )
    return result.rowcount
```

(`func` is already imported locally in several store helpers — follow the
file's pattern of importing inside the function or hoist once; match what the
file does at the first edit site.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && python -m pytest tests/test_store.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/doug/store.py api/tests/test_store.py
git commit -m "feat: token list/revoke/revoke-all store helpers"
```

### Task 8: List and revoke endpoints

**Files:**
- Modify: `api/doug/api.py` (add after `dispense_token`)
- Test: `api/tests/test_api.py`

**Interfaces:**
- Consumes: `tenancy.verify_org_admin`, `tenancy.verify_repos_admin`, `store.list_installation_tokens`, `store.revoke_installation_token`, `store.installation_token_repo_ids`.
- Produces:
  - `GET /v1/installations/tokens?owner=<login>` + `X-GitHub-Token` → `{"tokens": [...]}` masked rows (datetimes ISO, `scopes`/`repo_selection` verbatim, plus `repo_ids` for selected keys).
  - `DELETE /v1/installations/token/{token_id}?owner=<login>` or `?repos=a/b,a/c` + `X-GitHub-Token` → `{"revoked": true}`.
  - Proof rules: list = org-admin only. Revoke = org-admin for anything; repo-admin only for a `selected` key whose junction ids ⊆ ids of the proven repos.

- [ ] **Step 1: Write the failing tests**

```python
def test_list_tokens_requires_org_admin_and_masks(tmp_path, monkeypatch):
    _api_db(tmp_path, monkeypatch)
    _pepper_env(monkeypatch)
    store.upsert_installation(150424894, "drewjst", "User", "active")
    minted = tenancy.mint_key(
        150424894, repo_selection="all", repo_ids=[], label="dash",
        expires_in_days=0, minted_by="drewjst",
    )
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
    assert rows[0]["label"] == "dash" and rows[0]["last4"] == minted.last4
    body = r.text
    assert minted.token not in body and "token_hash" not in body


def test_management_endpoints_reject_doug_tokens_as_proof(tmp_path, monkeypatch):
    """Keys cannot manage keys: a leaked key must never outrun revocation.
    Management proof is a GitHub PAT, full stop."""
    _api_db(tmp_path, monkeypatch)
    _pepper_env(monkeypatch)
    store.upsert_installation(150424894, "drewjst", "User", "active")
    minted = tenancy.mint_key(
        150424894, repo_selection="all", repo_ids=[], label=None,
        expires_in_days=0, minted_by="drewjst",
    )
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && python -m pytest tests/test_api.py -k "list_tokens or revoke or management" -v`
Expected: FAIL — 405/404 route-not-found style failures.

- [ ] **Step 3: Implement**

```python
@app.get("/v1/installations/tokens")
def list_tokens(owner: str = "", x_github_token: str = Header("")) -> dict:
    """Masked key inventory. Org-admin (or account-owner) proof only — the
    list names every key's lookup/label/selection, which is exactly the map
    an attacker holding one repo's admin would want. X-Doug-Token is not
    accepted here or on revoke: keys cannot manage keys."""
    if not x_github_token:
        raise HTTPException(status_code=401, detail="X-GitHub-Token required")
    if not store.enabled():
        raise HTTPException(status_code=503, detail="no ledger configured")
    if not owner or "/" in owner:
        raise _not_found()
    installation_id = tenancy.verify_org_admin(x_github_token, owner)
    if installation_id is None:
        raise _not_found()
    rows = store.list_installation_tokens(installation_id)
    for row in rows:
        if row["repo_selection"] == "selected":
            row["repo_ids"] = sorted(store.installation_token_repo_ids(row["id"]))
    return {"tokens": jsonable_encoder(rows)}


@app.delete("/v1/installations/token/{token_id}")
def revoke_token(
    token_id: int,
    owner: str = "",
    repos: str = "",
    x_github_token: str = Header(""),
) -> dict:
    """Soft-revoke one key. Proof must cover the key's selection, mirroring
    mint: org-admin proof revokes anything; repo-admin proof revokes a
    'selected' key iff the proven repos cover every repo the key names."""
    if not x_github_token:
        raise HTTPException(status_code=401, detail="X-GitHub-Token required")
    if not store.enabled():
        raise HTTPException(status_code=503, detail="no ledger configured")
    if owner and "/" not in owner:
        installation_id = tenancy.verify_org_admin(x_github_token, owner)
        if installation_id is None or not store.revoke_installation_token(
            token_id, installation_id
        ):
            raise _not_found()
        return {"revoked": True}
    if repos:
        names = [r for r in repos.split(",") if r]
        if not names or len(names) > MAX_REPOS_PER_MINT:
            raise _not_found()
        parsed_repos = []
        for full in names:
            repo_owner, _, name = full.partition("/")
            if not repo_owner or not name or "/" in name:
                raise _not_found()
            parsed_repos.append((repo_owner, name))
        installation_id = tenancy.verify_repos_admin(x_github_token, parsed_repos)
        if installation_id is None:
            raise _not_found()
        by_name = {full_name: rid for rid, full_name in store.active_repos(installation_id)}
        try:
            proven_ids = {by_name[full] for full in names}
        except KeyError:
            raise _not_found()
        key_repo_ids = store.installation_token_repo_ids(token_id)
        # Repo-admin proof reaches ONLY 'selected' keys it fully covers. An
        # 'all' key has no junction rows → empty set → refused here, which
        # is exactly the point: killing the org key takes org-admin proof.
        if not key_repo_ids or not key_repo_ids <= proven_ids:
            raise _not_found()
        if not store.revoke_installation_token(token_id, installation_id):
            raise _not_found()
        return {"revoked": True}
    raise _not_found()
```

Add `from fastapi.encoders import jsonable_encoder` to `api.py` imports.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && python -m pytest tests/test_api.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/doug/api.py api/tests/test_api.py
git commit -m "feat: PAT-proof key list and revoke endpoints (keys cannot manage keys)"
```

### Task 9: Uninstall bulk-revokes

**Files:**
- Modify: `api/doug/api.py` (`_record_installation`, `deleted` branch, `:757-764`)
- Test: `api/tests/test_api.py`

**Interfaces:**
- Consumes: `store.revoke_all_installation_tokens`.
- Produces: uninstall stamps `revoked_at` on all live keys.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest tests/test_api.py -k bulk_revokes -v`
Expected: FAIL — resolve returns a context after reinstall (state is active again, nothing stamped the key).

- [ ] **Step 3: Implement**

In `_record_installation`'s `deleted` branch (`api.py:757-764`), after `set_installation_repos`:

```python
    elif action == "deleted":
        # (existing comment + set_installation_repos call stay)
        store.set_installation_repos(inst["id"], [], replace=True)
        # The live state check already ends access; this stamp is the audit
        # trail AND the reinstall guard — 'created' flips state back to
        # active, and without revoked_at every pre-uninstall key would
        # quietly resurrect with it.
        n = store.revoke_all_installation_tokens(inst["id"])
        if n:
            print(f"doug: uninstall revoked {n} key(s) for installation {inst['id']}", file=sys.stderr)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && python -m pytest tests/test_api.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/doug/api.py api/tests/test_api.py
git commit -m "feat: uninstall bulk-revokes keys — reinstall cannot resurrect them (MT2 audit half)"
```

---

## Slice C — queue id-unification (MT4), drift warning, ops

### Task 10: `?repo=` resolves through ids; MT4 consistency pin

**Files:**
- Modify: `api/doug/api.py` (`queue`, the `?repo=` block Task 5/6 left name-based)
- Test: `api/tests/test_api.py`

**Interfaces:**
- Consumes: `store.active_repos`, `ctx.repo_ids`, `store.latest_reviews(repo_ids=...)`.
- Produces: for tenant calls, `?repo=` resolves a full_name to a `github_repo_id` via ACTIVE `installation_repos` rows and both authorization and row filtering use that id. Operator calls keep the display-name filter (unscoped view, not a tenancy boundary).

- [ ] **Step 1: Write the failing tests**

```python
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
    # A verdict for a repo the installation no longer covers (state flip):
    _seed_verdict(repo="drewjst/gone", github_repo_id=333, installation_id=150424894, pr_number=9)
    minted = tenancy.mint_key(
        150424894, repo_selection="all", repo_ids=[], label=None,
        expires_in_days=0, minted_by="drewjst",
    )
    unfiltered = client.get("/v1/queue", headers={"x-doug-token": minted.token}).json()
    repos_served = {item["pr"]["repo"] for item in unfiltered["items"]}
    for full_name in repos_served:
        assert (
            client.get(
                "/v1/queue", params={"repo": full_name},
                headers={"x-doug-token": minted.token},
            ).status_code == 200
        ), f"unfiltered queue served {full_name} but ?repo= refuses it"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && python -m pytest tests/test_api.py -k "outside_the_keys_selection or one_source_of_truth" -v`
Expected: first FAILS (200 with empty items, not 404). Second may fail either direction — that disagreement is the MT4 bug being pinned.

- [ ] **Step 3: Implement**

In `queue`, replace the tenant-path `?repo=` name check (`api.py:487-492`) with
id resolution, and make `all`-keys' row filtering use live ids too (that is
what makes the consistency test hold when a repo's `installation_repos` state
flips while its verdicts remain):

```python
    repo_ids: frozenset[int] | None = None
    if ctx is not None:
        live = {full_name: rid for rid, full_name in store.active_repos(ctx.installation_id)}
        # The key's effective scope, in ids: its frozen selection (already
        # live-intersected by resolve) or, for 'all', everything live NOW.
        # installation_repos is the ONE source of truth — verdicts.repo and
        # full_name are display everywhere (MT4).
        effective = ctx.repo_ids if ctx.repo_ids is not None else frozenset(live.values())
        if repo is not None:
            rid = live.get(repo)
            if rid is None or rid not in effective:
                # 404, never an empty list: an empty list reads as "no
                # reviews yet" and confirms the repo's existence.
                raise HTTPException(status_code=404, detail="not found")
            effective = frozenset({rid})
        repo_ids = effective
```

and thread it through:

```python
            for row in store.latest_reviews(
                repo=repo if ctx is None else None,   # operator keeps the display filter
                installation_id=installation_id,
                repo_ids=repo_ids,
            )
```

- [ ] **Step 4: Run the whole suite**

Run: `cd api && python -m pytest tests/ -q`
Expected: green. `test_queue_selected_key_sees_only_its_repos_rows` (Task 6) still passes — same filter, tighter source.

- [ ] **Step 5: Commit**

```bash
git add api/doug/api.py api/tests/test_api.py
git commit -m "feat: queue repo authorization and filtering share installation_repos ids (MT4)"
```

### Task 11: Startup drift warning

**Files:**
- Modify: `api/doug/store.py` (one helper), `api/doug/api.py` (`_startup_reconcile`, `:37-65`)
- Test: `api/tests/test_store.py`, `api/tests/test_api.py`

**Interfaces:**
- Produces: `store.count_installations_referenced_by_verdicts() -> int` (DISTINCT non-NULL `verdicts.installation_id`); `_startup_reconcile` logs a loud warning when the tenancy ledger is empty while verdicts reference installations.

- [ ] **Step 1: Write the failing tests**

```python
# test_store.py
def test_count_installations_referenced_by_verdicts(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    _write_verdict(repo="drewjst/a", github_repo_id=111, installation_id=150424894, pr_number=1)
    _write_verdict(repo="drewjst/a", github_repo_id=111, installation_id=150424894, pr_number=2)
    _write_verdict(repo="ci/x", github_repo_id=None, installation_id=None, pr_number=3)
    assert store.count_installations_referenced_by_verdicts() == 1
```

```python
# test_api.py
def test_startup_warns_when_verdicts_reference_installations_the_ledger_lacks(
    tmp_path, monkeypatch, capsys
):
    """REVIEWING.md § 'A table only a webhook populates': prod sat for weeks
    with 33 verdicts and ZERO installations rows, and reconcile_all was a
    silent structural no-op. The next MT0-class state must be a loud line,
    not a quiet nothing."""
    _api_db(tmp_path, monkeypatch)
    _write_verdict(repo="drewjst/a", github_repo_id=111, installation_id=150424894, pr_number=1)
    monkeypatch.setattr(worker, "reconcile_all", lambda: 0)
    monkeypatch.setattr(worker, "drain", lambda: None)
    from doug.api import _startup_reconcile
    _startup_reconcile()
    err = capsys.readouterr().err
    assert "DRIFT" in err and "installation webhook" in err and "MT0" in err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && python -m pytest tests/test_store.py -k referenced tests/test_api.py -k DRIFT -v`
Expected: FAIL — `AttributeError` / assertion on missing stderr line.

- [ ] **Step 3: Implement**

```python
# store.py
def count_installations_referenced_by_verdicts() -> int:
    """How many distinct installations the verdicts ledger names. Compared
    against active_installations() at startup: verdicts referencing tenants
    the installations table has never heard of is the MT0 signature — a
    webhook that never arrived — and reconcile_all is silently dead."""
    engine = _get_engine()
    if engine is None:
        return 0
    from sqlalchemy import func

    with engine.connect() as conn:
        return int(
            conn.execute(
                select(func.count(func.distinct(verdicts.c.installation_id))).where(
                    verdicts.c.installation_id.is_not(None)
                )
            ).scalar_one()
        )
```

```python
# api.py, _startup_reconcile, before the reconcile_all call
    if store.enabled() and not store.active_installations():
        referenced = store.count_installations_referenced_by_verdicts()
        if referenced:
            print(
                f"doug: DRIFT — verdicts reference {referenced} installation(s) but the "
                "installations table is empty; reconcile_all and token dispense are "
                "structural no-ops. Redeliver the installation webhook (ROADMAP MT0).",
                file=sys.stderr,
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && python -m pytest tests/ -q`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add api/doug/store.py api/doug/api.py api/tests/
git commit -m "feat: startup drift warning when verdicts name installations the ledger lacks"
```

### Task 12: Deploy wiring and the operations doc

**Files:**
- Modify: `api/deploy/gcp.sh` (secret creation near `:44`, service-account binding loop `:103`, `--set-secrets` `:233`)
- Create: `docs/OPERATIONS.md`
- Modify: `docs/design/outcome-loop/ROADMAP.md` (§ MT statuses)

**Interfaces:** none — deploy + docs.

- [ ] **Step 1: gcp.sh**

Mirror the `doug-api-token` handling for the pepper, at each of the three sites:

- Near `:44` (secret creation block): `python3 -c "import base64,secrets;print(base64.b64encode(secrets.token_bytes(32)).decode())" | gcloud secrets create doug-token-pepper --data-file=- --project "$PROJECT" 2>/dev/null || echo "doug-token-pepper secret exists; leaving it"`
- `:103` loop: add `doug-token-pepper` to the list of secrets the **api** service account can access (NOT doug-web's block at `:116` — the web tier holds the operator token only).
- `:233` `--set-secrets`: append `,DOUG_TOKEN_PEPPER=doug-token-pepper:latest`.

- [ ] **Step 2: Write `docs/OPERATIONS.md`**

```markdown
# Operations runbook

## Tenant API keys

### Break-glass: revoke a tenant's keys (operator, SQL)

Soft revoke — rows are audit history, never DELETE:

    UPDATE installation_tokens SET revoked_at = NOW()
    WHERE installation_id = <id> AND revoked_at IS NULL;

Effective on the tenant's next request (resolve has no cache).

### Pepper rotation (rolling — never a flag-day)

1. Create the next secret version: `DOUG_TOKEN_PEPPER_V2` (base64, exactly
   32 bytes), bind it in gcp.sh's --set-secrets alongside V1.
2. Deploy. New mints now write hash_version=2; existing keys keep verifying
   under V1.
3. When no live rows carry hash_version=1
   (`SELECT COUNT(*) FROM installation_tokens WHERE hash_version=1 AND revoked_at IS NULL`),
   drop the V1 binding.
Never remove a pepper version that live rows still reference — those keys
would die unverifiable (fail closed, not fail open).

### MT0-class drift

If startup logs `doug: DRIFT — verdicts reference N installation(s)...`:
the `installation` webhook never populated the ledger. Redeliver it (App
settings → Advanced → Recent Deliveries). Do NOT uninstall/reinstall —
GitHub mints a new installation_id and orphans every verdict.
```

- [ ] **Step 3: ROADMAP § MT** — mark MT1/MT2/MT4/MT5 closed with one-line
pointers to the spec (`docs/superpowers/specs/2026-08-04-tenant-api-keys-design.md`)
and the closing tasks; MT0/MT3 stay open. Follow the section's existing prose style.

- [ ] **Step 4: Verify**

Run: `bash -n api/deploy/gcp.sh` (syntax only) and `cd api && python -m pytest tests/ -q`.
Expected: both clean.

- [ ] **Step 5: Commit**

```bash
git add api/deploy/gcp.sh docs/OPERATIONS.md docs/design/outcome-loop/ROADMAP.md
git commit -m "ops: pepper secret wiring, runbook, ROADMAP MT statuses"
```

---

## Self-review notes (already applied)

- Spec coverage: §3→Task 2, §4→Tasks 1+3, §5→Tasks 4+6, §6→Tasks 5+6+10, §7→Tasks 7+8+9, §10's pins are distributed into each task's tests (chain order T5, dummy HMAC T5, append T2/T6, quota order T4, proof coverage T4/T6, MT4 consistency T10, deny-log T6, cap fail-open T6, drift warning T11), §11→Tasks 2+12, §12 slice order = task order.
- Deliberate deviations from the spec, both argued inline: the daily mint cap counts `installation_tokens.created_at` rows instead of adding a counter table (same fail-open contract, one less table); `selected`-mint resolves repo names→ids through the ledger and refuses unknown names (the junction stores ids; GitHub has already vouched for the repos).
- Known intermediate state: after Slice A, `?repo=` on a sibling active repo returns an empty 200 for a selected key (existence disclosure inside one installation only); Task 10 closes it. Do not "fix" it early — Task 10's first test documents the gap.
- `test_api.py` fixture names (`_api_db`, `_seed_verdict`, `_write_verdict`) are stand-ins for that file's existing helpers — locate and reuse the real ones at each task's Step 1; do not invent parallel fixtures.
