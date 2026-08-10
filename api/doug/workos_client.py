"""The four WorkOS calls the bind endpoint makes, and nothing else.

Deliberately hand-rolled over httpx rather than pulling in the WorkOS Python
SDK, for the same reason session_auth builds its own JWKS URL: this is four
documented endpoints, and an SDK dependency for four request lines would put
a large surface into an image whose only other outbound client is githubkit.

Every call carries `Authorization: Bearer $WORKOS_API_KEY`. That key reads
every tenant's identity data, so it appears in exactly one place — the header
built in `_request` — and never in a log line, an exception message, or a
returned value. `_send` below is the ONE network boundary in this module; the
test suite replaces it (or `_request`) wholesale, so no test reaches WorkOS.

Endpoints used (verified against live docs 2026-08-09 — do not add others
without the same check):

    GET  /user_management/users/{user_id}/identities      -> [].idp_id
    GET  /organizations/external_id/{external_id}
    POST /organizations                                   {name, external_id}
    POST /user_management/organization_memberships        {user_id, organization_id}
"""

import os
import sys

import httpx

BASE_URL = "https://api.workos.com"

# One bind is four requests at most and runs behind a browser click, so a
# generous per-request ceiling is fine; what matters is that there IS one —
# an unbounded connect would hold a Cloud Run request (and, under the bind
# lock, a Postgres connection) for as long as WorkOS is unreachable.
TIMEOUT_S = 10.0


class WorkOSNotConfigured(Exception):
    """Raised when WORKOS_API_KEY is absent. Mirrors
    session_auth.SessionAuthNotConfigured and tenancy.KeysNotConfigured: the
    caller renders it as a named 503, so a deployment missing its key is
    diagnosable instead of looking like every caller failing an identity
    check."""


class WorkOSError(Exception):
    """An upstream failure — a transport error or an unexpected status.

    Distinct from a None return on purpose. None means "WorkOS answered, and
    the answer is no"; this means "WorkOS did not answer". The bind endpoint
    renders the first as a refusal and the second as a 503, because telling a
    real installer their proof was wrong during someone else's incident is
    the more expensive mistake.
    """


def external_id_for(installation_id: int) -> str:
    """The WorkOS `external_id` for one GitHub App installation.

    A pure function of the installation id, and that is the whole security
    property: the organization key can never be supplied by a caller, so
    binding a victim's org id before they do — which Task 1's UNIQUE index
    would then make permanent — is not a request anyone can make.
    """
    return f"gh-inst-{installation_id}"


def _send(method: str, url: str, *, headers: dict, json: dict | None) -> httpx.Response:
    """The only place this module touches the network.

    Its own function so tests can replace exactly this and still exercise
    every header, path and status-code branch above it — the same seam
    session_auth._jwks provides for JWKS.
    """
    return httpx.request(method, url, headers=headers, json=json, timeout=TIMEOUT_S)


def _request(method: str, path: str, *, json: dict | None = None) -> httpx.Response:
    """One authenticated call. Raises before sending anything when the key is
    absent, and translates transport failures into WorkOSError so callers
    handle one exception type rather than httpx's tree."""
    api_key = os.environ.get("WORKOS_API_KEY")
    if not api_key:
        raise WorkOSNotConfigured()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        return _send(method, f"{BASE_URL}{path}", headers=headers, json=json)
    except httpx.HTTPError as e:
        # The exception is re-raised without its message: httpx puts the URL
        # in some of them, never the header, but the rule here is that
        # nothing derived from a request carrying the key gets re-emitted.
        raise WorkOSError(f"workos {method} {path} failed ({type(e).__name__})") from e


def _failure(method: str, path: str, response: httpx.Response) -> WorkOSError:
    """A WorkOSError naming what was asked and what came back — status and
    method only. Never the response body (it can echo request content) and
    never the key."""
    return WorkOSError(f"workos {method} {path} returned {response.status_code}")


def _entries(payload) -> list[dict]:
    """The list out of a WorkOS list response.

    The identities endpoint is documented as a bare array, while WorkOS's
    other list endpoints answer {"data": [...]}. Both are accepted because
    only one of them was verifiable from the docs, and guessing wrong would
    read as "this user has no GitHub identity" — a silent, permanent refusal
    rather than a visible error.
    """
    if isinstance(payload, dict):
        payload = payload.get("data")
    return [entry for entry in payload or [] if isinstance(entry, dict)]


def github_user_id_for(workos_user_id: str) -> str | None:
    """This WorkOS user's GitHub identity id, verbatim, or None.

    Returned as the raw string it arrived as. `idp_id`'s format for a GitHub
    connection is UNDOCUMENTED and was never measured (WorkOS documents it
    only as "a unique identifier from the external provider", with a
    Microsoft example), so this function does not normalise it, parse it, or
    guess a fallback — the caller compares it and says so loudly when it is
    not what the inference expects.

    The identity is selected only when WorkOS explicitly labels exactly one
    row as both OAuth and GitHub. A Google identity's idp_id is a Google
    subject id, and an unlabeled numeric id is not evidence of GitHub
    authority. Missing fields, other identity types, and ambiguous matching
    rows all fail closed.
    """
    path = f"/user_management/users/{workos_user_id}/identities"
    response = _request("GET", path)
    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        raise _failure("GET", path, response)
    identities = _entries(response.json())
    github = [
        identity
        for identity in identities
        if identity.get("type") == "OAuth"
        and "github" in str(identity.get("provider") or "").lower()
    ]
    if len(github) != 1:
        return None
    idp_id = github[0].get("idp_id")
    return str(idp_id) if idp_id is not None else None


def find_organization(external_id: str) -> str | None:
    """The organization already registered under this external id, or None."""
    path = f"/organizations/external_id/{external_id}"
    response = _request("GET", path)
    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        raise _failure("GET", path, response)
    organization_id = response.json().get("id")
    if not organization_id:
        raise _failure("GET", path, response)
    return str(organization_id)


def ensure_organization(name: str, external_id: str) -> str:
    """Get-or-create the organization for one installation.

    Inherently TOCTOU — two binds of the same installation can both find
    nothing. `external_id` is unique at WorkOS, so the loser gets a conflict,
    which is "already done", not "failed": it re-reads and returns the peer's
    organization, the same way store.upsert_installation treats its own
    insert race. The bind endpoint additionally serialises this behind a
    Postgres advisory lock, which covers the two-instances-one-installation
    case; this handles what a lock cannot (a WorkOS-side duplicate).
    """
    found = find_organization(external_id)
    if found is not None:
        return found
    response = _request("POST", "/organizations", json={"name": name, "external_id": external_id})
    if response.status_code in (409, 422):
        peer = find_organization(external_id)
        if peer is not None:
            return peer
        raise _failure("POST", "/organizations", response)
    if response.status_code >= 400:
        raise _failure("POST", "/organizations", response)
    organization_id = response.json().get("id")
    if not organization_id:
        raise _failure("POST", "/organizations", response)
    return str(organization_id)


def _says_already_exists(response: httpx.Response) -> bool:
    """Whether a 4xx is WorkOS saying 'this already exists'.

    409 is that answer on its own. 422 is not: WorkOS uses it for validation
    failures generally, so accepting every 422 as success would let an
    invalid organization id return 204 with no membership written — a bind
    that looks complete and shows the tenant nothing. Only a 422 that names
    the duplicate is read as success; anything else raises.
    """
    if response.status_code == 409:
        return True
    if response.status_code != 422:
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    text = f"{body.get('code', '')} {body.get('message', '')}".lower()
    return "already" in text or "exists" in text


def ensure_membership(workos_user_id: str, organization_id: str) -> None:
    """Put this user in this organization, or confirm they already are.

    A conflict is success: `installation.created` is replayable from GitHub's
    Redeliver button, and a second bind by the same person must not 500 on
    their own membership.
    """
    path = "/user_management/organization_memberships"
    response = _request(
        "POST", path, json={"user_id": workos_user_id, "organization_id": organization_id}
    )
    if _says_already_exists(response):
        print(
            f"doug: workos membership already present for organization={organization_id}",
            file=sys.stderr,
        )
        return
    if response.status_code >= 400:
        raise _failure("POST", path, response)
