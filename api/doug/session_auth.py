"""Resolve a signed-in browser session to a tenant scope.

WorkOS holds identity; GitHub holds entitlement; Postgres arbitrates. This
module only turns a verified AuthKit JWT into an installation_id — the
scope itself comes from tenancy.live_scope, so a session and a machine key
apply the same liveness and repo intersection (tenancy.py's SessionContext
docstring).

AuthKit access tokens carry no `aud` claim and no GitHub user id (verified
against a live token, see the Task 4 report). `org_id` is present only when
the caller has an organization selected — ABSENT on a normal first sign-in,
not an edge case — so its absence is read as "no tenant yet", never as
license to guess one.
"""

import os
import sys

import jwt
from jwt import PyJWKClient

from . import entitlements, store, tenancy

SESSION_SCOPES: tuple[str, ...] = ("queue:read", "receipt:read")

_jwks_client: PyJWKClient | None = None


class SessionAuthNotConfigured(Exception):
    """Raised when WORKOS_CLIENT_ID is absent. Mirrors tenancy.KeysNotConfigured:
    the caller renders this as 503, so a deployment missing its WorkOS client
    id fails loudly and diagnosably rather than silently refusing every
    session (which would look identical to a forged token)."""


def _jwks() -> PyJWKClient:
    """The JWKS client, built once and cached. The URL shape is WorkOS's
    documented per-client JWKS endpoint; the WorkOS Python SDK is not a
    repo dependency and adding it for one URL string is not warranted."""
    global _jwks_client
    if _jwks_client is None:
        client_id = os.environ.get("WORKOS_CLIENT_ID")
        if not client_id:
            raise SessionAuthNotConfigured()
        _jwks_client = PyJWKClient(f"https://api.workos.com/sso/jwks/{client_id}")
    return _jwks_client


def verify_session_claims(bearer: str) -> dict | None:
    """Verify an AuthKit JWT's signature and expiry, and return its claims.

    Deliberately weaker than resolve_session: it proves WHO is signed in and
    says nothing about what they may see. Bind needs exactly this, because it
    runs BEFORE any organization exists — creating one is what bind does — so
    resolve_session (which fails closed without org_id) would be circular.
    Never use this for a data read; use resolve_session, which additionally
    resolves and live-intersects a tenant scope.

    Two separate try/except blocks on purpose, each with its own log line —
    same shape as tenancy.verify_admin's caller-check / installation-lookup
    split. A JWKS lookup failure (network outage, or WorkOS not returning a
    matching key) and a token that fails decode/signature/exp verification
    are different operational events: the first means Doug's own
    configuration or WorkOS itself is unwell, the second means someone
    presented a bad credential. Collapsing them into one bare `except` would
    make a production outage indistinguishable from routine attack noise.
    The token itself is never logged in either branch.
    """
    if not bearer:
        return None
    token = bearer[7:] if bearer.lower().startswith("bearer ") else bearer

    try:
        signing_key = _jwks().get_signing_key_from_jwt(token).key
    except SessionAuthNotConfigured:
        raise
    except Exception as e:  # noqa: BLE001 — any failure here is "no usable key"
        print(
            f"doug: session auth denied at the JWKS lookup "
            f"({type(e).__name__}: {str(e)[:200]})",
            file=sys.stderr,
        )
        return None

    try:
        return jwt.decode(
            token, signing_key, algorithms=["RS256"], options={"require": ["exp"]}
        )
    except Exception as e:  # noqa: BLE001 — any failure here is "not a valid token"
        print(
            f"doug: session auth denied at token verification "
            f"({type(e).__name__}: {str(e)[:200]})",
            file=sys.stderr,
        )
        return None


def resolve_session(bearer: str) -> tenancy.SessionContext | None:
    """Map a bearer token to its live session context, or None.

    The verification half lives in verify_session_claims above (bind shares
    it); everything below is the tenant resolution this function adds on top,
    and which a session must pass before it may read anything.
    """
    claims = verify_session_claims(bearer)
    if claims is None:
        return None

    org_id = claims.get("org_id")
    workos_user_id = claims.get("sub")
    if not isinstance(workos_user_id, str) or not workos_user_id:
        return None
    if not org_id:
        # Absent whenever no organization is selected — the NORMAL first
        # sign-in state, not an edge case. Fail closed; NEVER default to
        # "the first installation".
        return None
    installation_id = store.installation_id_for_workos_org(org_id)
    if installation_id is None:
        return None
    claim = store.session_entitlement_for(workos_user_id, installation_id)
    if claim is None or entitlements.is_stale(claim["derived_at"]):
        return None
    scope = tenancy.live_scope(installation_id, claim["repo_ids"])
    if scope is None:
        return None
    return tenancy.SessionContext(
        installation_id=installation_id, repo_ids=scope, scopes=SESSION_SCOPES
    )
