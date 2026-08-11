"""Resolve a signed-in browser session to a tenant scope.

WorkOS holds identity; GitHub holds entitlement; Postgres arbitrates. This
module only turns a verified AuthKit JWT into an installation_id — the
scope itself comes from tenancy.live_scope, so a session and a machine key
apply the same liveness and repo intersection (tenancy.py's SessionContext
docstring).

AuthKit access tokens carry no `aud` claim and no GitHub user id (verified
against a live token, see the Task 4 report), so provenance is pinned by the
signature against Doug's client-scoped JWKS plus the exact `client_id` claim;
the issuer is additionally required to be a WorkOS AuthKit origin. `org_id`
is present only when the caller has an organization selected — ABSENT on a
normal first sign-in, not an edge case — so its absence is read as "no tenant
yet", never as license to guess one.
"""

import os
import re
import sys

import jwt
from jwt import PyJWKClient

from . import entitlements, store, tenancy

SESSION_SCOPES: tuple[str, ...] = ("queue:read", "receipt:read")

# WorkOS documents api.workos.com as the legacy access-token issuer; Doug's
# earlier live AuthKit receipt used auth.workos.com. Current hosted tokens
# scope the issuer to an application: the client id in that issuer PATH names
# the ENVIRONMENT'S DEFAULT APPLICATION — the issuing authority — which is not
# derivable from Doug's own configuration. PR #85 derived it from
# WORKOS_CLIENT_ID and production kept rejecting real sessions, because which
# application a token is FOR is the `client_id` CLAIM, not the issuer suffix.
# So the hosted application issuer is validated structurally below
# (_APPLICATION_ISSUER), while the claim that actually pins the application
# stays an exact match in verify_session_claims. A structural issuer admits
# nothing by itself: the signature must already verify against Doug's
# client-scoped JWKS, and the `client_id` claim must equal Doug's exactly.
# Custom AuthKit domains must still be pinned explicitly with WORKOS_ISSUER,
# which narrows acceptance to that single origin.
_DEFAULT_WORKOS_ISSUERS = (
    "https://api.workos.com",
    "https://api.workos.com/",
    "https://auth.workos.com",
    "https://auth.workos.com/",
)

# Both hosted bases can carry the application path: Doug has live receipts
# from each base host, so pinning one would just re-run this incident on the
# other. fullmatch anchors both ends; no \A/\Z needed.
_APPLICATION_ISSUER = re.compile(
    r"https://(api|auth)\.workos\.com/user_management/client_[0-9A-Za-z]+/?"
)

_jwks_client: PyJWKClient | None = None
_jwks_client_id: str | None = None


class SessionAuthNotConfigured(Exception):
    """Raised when WORKOS_CLIENT_ID is absent. Mirrors tenancy.KeysNotConfigured:
    the caller renders this as 503, so a deployment missing its WorkOS client
    id fails loudly and diagnosably rather than silently refusing every
    session (which would look identical to a forged token)."""


def _client_id() -> str:
    client_id = os.environ.get("WORKOS_CLIENT_ID")
    if not client_id:
        raise SessionAuthNotConfigured()
    return client_id


def _issuer_allowed(issuer: object) -> bool:
    configured = os.environ.get("WORKOS_ISSUER")
    if not isinstance(issuer, str):
        return False
    if configured:
        normalized = configured.rstrip("/")
        return issuer in (normalized, f"{normalized}/")
    if issuer in _DEFAULT_WORKOS_ISSUERS:
        return True
    return _APPLICATION_ISSUER.fullmatch(issuer) is not None


def _jwks() -> PyJWKClient:
    """The JWKS client, cached together with the client id that selected it.

    The URL shape is WorkOS's documented per-client JWKS endpoint; the WorkOS
    Python SDK is not a repo dependency and adding it for one URL string is
    not warranted.
    """
    global _jwks_client, _jwks_client_id
    client_id = _client_id()
    if _jwks_client is None or _jwks_client_id != client_id:
        _jwks_client = PyJWKClient(f"https://api.workos.com/sso/jwks/{client_id}")
        _jwks_client_id = client_id
    return _jwks_client


def verify_session_claims(bearer: str) -> dict | None:
    """Verify an AuthKit JWT's signature, expiry, issuer, and client id.

    Deliberately weaker than resolve_session: it proves WHO is signed in and
    says nothing about what they may see. Bind needs exactly this, because it
    runs BEFORE any organization exists — creating one is what bind does — so
    resolve_session (which fails closed without org_id) would be circular.
    Never use this for a data read; use resolve_session, which additionally
    resolves and live-intersects a tenant scope.

    Two separate try/except blocks on purpose, each with its own log line —
    same shape as tenancy.verify_admin's caller-check / installation-lookup
    split. A JWKS lookup failure (network outage, or WorkOS not returning a
    matching key) and a token that fails claim/signature/expiry verification
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
        client_id = _client_id()
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
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            options={"require": ["exp", "iss"]},
        )
        if not _issuer_allowed(claims.get("iss")):
            # The offending value goes into the message on purpose. PyJWT's
            # own InvalidIssuerError says only "Invalid issuer", which left
            # two production 401 rounds undiagnosable — the log line below
            # carries this message, and an issuer is a URL, never a secret.
            raise jwt.InvalidIssuerError(f"untrusted issuer {claims.get('iss')!r}")
        if claims.get("client_id") != client_id:
            raise jwt.InvalidTokenError("unexpected client_id claim")
        return claims
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
