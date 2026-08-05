"""Per-installation API tokens: mint, resolve, and the GitHub proof behind them.

Deliberately free of any FastAPI import. The v1.5 MCP garden is a separate
Cloud Run service running this same image (design-lock.md:31), and
design-lock.md:65 records that the token mint survived the tenant-page cut
"because its consumers are the API and later MCP" — so verification has to be
importable without dragging in the web app.

Only the peppered HMAC-SHA256 of a token's secret half is ever persisted
(keyformat.py owns the doug_live_ wire format; hash_secret below owns the
peppering). The plaintext is returned once by mint_key() and is unrecoverable
afterwards, which makes "we cannot show you that token again" a property of
the schema rather than a policy someone can relax.
"""

import base64
import binascii
import hashlib
import hmac
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

from githubkit import GitHub

from . import app_auth, keyformat, store


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
    # strip(): every natural secret pipeline (print | gcloud secrets
    # create) appends a newline, and b64decode(validate=True) refuses it —
    # prod 503'd every mint until the secret was re-cut (2026-08-05).
    # Whitespace carries no entropy; the 32-byte check below is the gate.
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return None
    try:
        decoded = base64.b64decode(raw, validate=True)
    except (ValueError, binascii.Error):
        return None
    return decoded if len(decoded) == 32 else None


def _current_hash_version() -> int:
    """Highest contiguously configured pepper version, scanning up from 1 — a
    gap ends the scan, so configure versions without gaps (the rotation runbook
    does). New mints use this; old keys keep verifying under their recorded
    version, which is what makes pepper rotation rolling instead of a flag-day."""
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


def _caller_client(pat: str) -> GitHub:
    """A client authenticated as the caller, not as Doug. Its own name so
    tests can replace it without patching githubkit globally."""
    return GitHub(pat)


def verify_admin(pat: str, owner: str, repo: str) -> int | None:
    """Prove the caller administers a repo Doug is installed on.

    THE CALL ORDER IS LOAD-BEARING. Two GitHub calls happen here and they
    spend different quotas: the PAT call spends the CALLER'S, the app-JWT
    call spends DOUG'S — the shared 5,000/hr pool that the review path needs
    to mint installation tokens, and that was exhausted twice on 2026-08-02.
    Dispense is a public endpoint on an --allow-unauthenticated service, so
    doing the app call first would hand an anonymous caller a loop that
    drains Doug's quota. Checking the caller's own credential first means an
    attacker burns their own budget and reaches nothing of ours.

    Returns None for every failure, deliberately without distinguishing
    them: the endpoint renders all of these as 404, so a caller cannot use
    the difference to discover whether a private repo exists.
    """
    # 1. The caller's own credential and the caller's own quota.
    #
    # Every GitHub client below is bound to a local for the duration of its
    # call. githubkit's .rest namespace holds the client weakly, and a
    # construct-and-chain temporary (`GitHub(pat).rest.x.y()`) can be
    # garbage-collected mid-call — "GitHub client has already been
    # collected", seen in prod on 2026-08-05 at the identity check. Tests
    # stub _caller_client wholesale, so only prod traffic exercises this.
    try:
        caller = _caller_client(pat)
        seen = caller.rest.repos.get(owner=owner, repo=repo)
    except Exception as e:  # noqa: BLE001 — any failure is "cannot prove it"
        # Collapsed to 404 for the caller on purpose (see the docstring), but
        # the operator still needs to tell a GitHub outage or a rate-limit 403
        # apart from a genuine refusal. Undifferentiated to them, diagnosable
        # to us. The PAT is never logged — only what was asked and what broke.
        print(
            f"doug: dispense denied {owner}/{repo} at the caller check "
            f"({type(e).__name__}: {str(e)[:200]})",
            file=sys.stderr,
        )
        return None
    permissions = getattr(seen.parsed_data, "permissions", None)
    # Only an explicit True proceeds. githubkit models an absent field as a
    # sentinel rather than None, so a truthiness test would admit it.
    if getattr(permissions, "admin", False) is not True:
        return None

    # 2. Doug's identity, and only now Doug's quota.
    if not app_auth.enabled():
        return None
    try:
        app = app_auth.app_client()
        found = app.rest.apps.get_repo_installation(owner=owner, repo=repo)
    except Exception as e:  # noqa: BLE001 — 404 here means Doug is not installed
        # Same reasoning as the caller check above. This one is the more
        # valuable line of the two: a 404 here is the ordinary "Doug is not
        # installed there" case, so anything that is NOT a 404 — a 5xx, a
        # timeout, a rate limit — means Doug's own app credentials or quota
        # are in trouble, and nothing else in the system would say so.
        print(
            f"doug: dispense denied {owner}/{repo} at the installation lookup "
            f"({type(e).__name__}: {str(e)[:200]})",
            file=sys.stderr,
        )
        return None
    installation_id = getattr(found.parsed_data, "id", None)
    return installation_id if isinstance(installation_id, int) else None


class MintedKey(NamedTuple):
    token: str
    token_id: int
    last4: str
    expires_at: datetime | None


def caller_login(pat: str) -> str | None:
    """GET /user on the caller's own quota. Used for minted_by attribution
    and as the cheap first hop of the User-install proof."""
    try:
        caller = _caller_client(pat)  # bound: see verify_admin's lifetime note
        me = caller.rest.users.get_authenticated()
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
            caller = _caller_client(pat)  # bound: see verify_admin's lifetime note
            membership = caller.rest.orgs.get_membership_for_authenticated_user(org=owner)
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
        app = app_auth.app_client()  # bound: see verify_admin's lifetime note
        if is_owner:
            found = app.rest.apps.get_user_installation(username=owner)
        else:
            found = app.rest.apps.get_org_installation(org=owner)
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
