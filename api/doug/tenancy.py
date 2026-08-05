"""Per-installation API tokens: mint, resolve, and the GitHub proof behind them.

Deliberately free of any FastAPI import. The v1.5 MCP garden is a separate
Cloud Run service running this same image (design-lock.md:31), and
design-lock.md:65 records that the token mint survived the tenant-page cut
"because its consumers are the API and later MCP" — so verification has to be
importable without dragging in the web app.

Only sha256(token) is ever persisted. The plaintext is returned once by mint()
and is unrecoverable afterwards, which makes "we cannot show you that token
again" a property of the schema rather than a policy someone can relax.
"""

import base64
import binascii
import hashlib
import hmac
import os
import secrets
import sys

from githubkit import GitHub
from sqlalchemy import select, update

from . import app_auth, store

# Greppable in a leaked-secret sweep, and the shape GitHub's secret scanning
# would key on if Doug ever registers a pattern.
TOKEN_PREFIX = "doug_"


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


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def mint(installation_id: int) -> str | None:
    """Issue a token for an existing installation. Returns the plaintext
    exactly once, or None when storage is off or the installation is unknown.

    An UPDATE rather than an upsert on purpose: a token for an installation
    with no row would resolve to an id that no tenancy backs, so the absence
    of a row is a refusal, not something to paper over.
    """
    engine = store._get_engine()
    if engine is None:
        return None
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    with engine.begin() as conn:
        result = conn.execute(
            update(store.installations)
            .where(store.installations.c.installation_id == installation_id)
            .values(token_hash=_hash(token))
        )
    if result.rowcount == 0:
        return None
    return token


def resolve(token: str) -> int | None:
    """Map a presented token to its installation id, or None.

    The prefix check short-circuits before any query, so the operator token
    and ordinary junk never reach storage. Lookup is by digest: the compared
    value is already a hash, so an equality match leaks nothing a timing
    attack could use — an attacker would need a preimage, not a clock.

    token_hash is NULL until an installation mints, and SQL equality never
    matches NULL, so un-minted installations are unreachable by design.
    """
    if not token.startswith(TOKEN_PREFIX):
        return None
    engine = store._get_engine()
    if engine is None:
        return None
    with engine.connect() as conn:
        return conn.execute(
            select(store.installations.c.installation_id).where(
                store.installations.c.token_hash == _hash(token)
            )
        ).scalar_one_or_none()


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
    try:
        seen = _caller_client(pat).rest.repos.get(owner=owner, repo=repo)
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
        found = app_auth.app_client().rest.apps.get_repo_installation(owner=owner, repo=repo)
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
