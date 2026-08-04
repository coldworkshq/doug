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

import hashlib
import secrets

from githubkit import GitHub
from sqlalchemy import select, update

from . import app_auth, store

# Greppable in a leaked-secret sweep, and the shape GitHub's secret scanning
# would key on if Doug ever registers a pattern.
TOKEN_PREFIX = "doug_"


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
    except Exception:  # noqa: BLE001 — any failure is "cannot prove it"
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
    except Exception:  # noqa: BLE001 — 404 here means Doug is not installed
        return None
    installation_id = getattr(found.parsed_data, "id", None)
    return installation_id if isinstance(installation_id, int) else None
