"""What a signed-in user is entitled to — derived from their identity
provider, stored without the credential that proved it.

WHY THIS EXISTS. `authkit-nextjs` hands the provider's `oauthTokens` to
`handleAuth`'s `onSuccess` and nowhere else: `withAuth()` does not return
them and the session does not carry them. The dashboard runs on a LATER
request, so by the time a read needs to know which repos this person may
see, the GitHub token is gone. The scope is therefore derived once, at
sign-in, and persisted — the token is used and discarded.

THREE PROPERTIES, and they are the whole module:

1. PROVIDER-NEUTRAL BY CONSTRUCTION. `derive` dispatches on a provider name
   and GitHub is one deriver among however many there turn out to be. The
   storage side keys on the WorkOS user id (store.replace_session_
   entitlements), never a GitHub user id, so a second connection means
   adding a function here — not reshaping sessions. A provider with no
   deriver answers "no tenants" and says so on stderr; it never raises.

2. NO CREDENTIAL AT REST. The token arrives as an argument, is used to make
   the calls below, and is discarded. It appears in exactly one place — the
   header built in `_request` — and never in a log line, an exception
   message, a return value or a stored row. Same rule, same shape as
   workos_client's WORKOS_API_KEY.

3. STALENESS HAS A HARD CEILING. `WORKOS_COOKIE_MAX_AGE` defaults to ~400
   days, so "bounded by the session" is not a bound at all. A derived scope
   carries `derived_at` and `is_stale` calls it dead after TTL (8h — the
   measured GitHub token TTL, so this is no less fresh than having kept the
   token would have been).

WHAT IS *NOT* STALE, and must not be overstated: tenancy.live_scope
intersects every read against the live ledger, so a suspended installation
or a repo removed from it is refused immediately regardless of what is
stored here. Only GitHub-side access revocation — someone losing repo
access at GitHub without the installation changing — waits out the TTL.

Endpoints used (both documented as returning at most 100 per page):

    GET /user/installations                        -> .installations[]
    GET /user/installations/{id}/repositories      -> .repositories[]

Hand-rolled over httpx rather than githubkit, for the reason workos_client
gives: the caller's token is a bearer credential for their whole account,
and a single `_send` boundary is what lets it live in one header, be
absent from every error path, and be stubbed whole in tests. githubkit is
Doug's own App identity (app_auth) — a different credential with a
different blast radius.
"""

import sys
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

import httpx

from . import app_auth

GITHUB_API = "https://api.github.com"

# Sign-in is a person waiting on a redirect, and a large account can need
# several pages, so the ceiling is per-request rather than generous overall.
TIMEOUT_S = 10.0

# GitHub's documented maximum. Anything smaller only multiplies round trips.
PER_PAGE = 100

# 20 pages of installations, and 20 of repositories per installation. A real
# account is one page of each; this exists so a paging bug (or a response
# that never shortens) cannot spin a sign-in forever. Hitting it is logged,
# because a truncated scope is otherwise indistinguishable from a small one.
MAX_PAGES = 20

# The measured GitHub user-token lifetime. Storing the derived scope for
# longer than the credential behind it would have lived is what turns
# "persist the scope, not the token" into a weaker promise than it sounds.
TTL = timedelta(hours=8)


class Tenant(NamedTuple):
    """One installation this user reaches, and the repositories they reach
    through it. repo_ids is explicit and sorted for BOTH repository_selection
    values — a session's scope is never installation-wide (see
    tenancy.SessionContext), so 'all' has to be resolved to ids like
    'selected' is."""

    installation_id: int
    repo_ids: tuple[int, ...]


class EntitlementsNotConfigured(Exception):
    """Raised when DOUG_GITHUB_APP_ID is absent. Mirrors
    session_auth.SessionAuthNotConfigured and workos_client.WorkOSNotConfigured:
    the caller renders it as a named 503, because without the app id there is
    no safe answer — see `_derive_github`."""


class ProviderError(Exception):
    """The provider did not answer, or answered with something unusable.

    Distinct from an empty result on purpose. Empty means "GitHub answered,
    and this user reaches nothing"; this means "GitHub did not answer". The
    difference matters more here than almost anywhere else in the codebase,
    because the empty answer gets WRITTEN — reading an outage as "entitled to
    nothing" would erase a real tenant's scope during someone else's incident.
    """


class ProviderTokenRejected(ProviderError):
    """The provider refused the caller's own credential (401).

    A subclass because it is a ProviderError to anyone who only cares that
    derivation failed, and its own type to the endpoint, which turns it into
    a 401 rather than a 503: an expired token is something the caller can fix
    by signing in again, and telling them "try later" would be wrong.
    """


def _send(url: str, *, headers: dict, params: dict) -> httpx.Response:
    """The only place this module touches the network.

    Its own function so tests can replace exactly this and still exercise
    every header, path, page and status-code branch above it — the same seam
    workos_client._send provides for WorkOS.
    """
    return httpx.get(url, headers=headers, params=params, timeout=TIMEOUT_S)


def _request(path: str, token: str, *, page: int) -> dict:
    """One page of one GitHub read, on the CALLER's token and the caller's
    quota — never Doug's App credentials, which is why this does not go
    through app_auth.

    The token is written into the header here and referred to nowhere else in
    this module. Transport failures become ProviderError so callers handle
    one exception type instead of httpx's tree, and the original message is
    dropped rather than re-raised: httpx puts the URL in some of them, never
    the header, but nothing derived from a request carrying a credential gets
    re-emitted.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        response = _send(
            f"{GITHUB_API}{path}", headers=headers, params={"per_page": PER_PAGE, "page": page}
        )
    except httpx.HTTPError as e:
        raise ProviderError(f"github GET {path} failed ({type(e).__name__})") from e
    if response.status_code == 401:
        raise ProviderTokenRejected(f"github GET {path} refused the caller's credential")
    if response.status_code >= 400:
        raise ProviderError(f"github GET {path} returned {response.status_code}")
    try:
        payload = response.json()
    except ValueError as e:
        raise ProviderError(f"github GET {path} returned an unreadable body") from e
    return payload if isinstance(payload, dict) else {}


def _entries(path: str, token: str, key: str) -> list[dict]:
    """Every entry under `key`, following pages until one comes back short.

    Short-page termination rather than Link-header parsing: both endpoints
    here are documented as page/per_page, and a short page is the same signal
    on either. total_count is deliberately NOT trusted as the stopping
    condition — it counts what exists, and these endpoints answer with what
    THIS user reaches, which is the smaller number for a 'selected'
    installation.
    """
    collected: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        payload = _request(path, token, page=page)
        entries = [e for e in payload.get(key) or [] if isinstance(e, dict)]
        collected.extend(entries)
        if len(entries) < PER_PAGE:
            return collected
    print(
        f"doug: entitlement derivation stopped at the {MAX_PAGES}-page ceiling for {path} — "
        f"the scope below is TRUNCATED, not complete",
        file=sys.stderr,
    )
    return collected


def _derive_github(token: str) -> list[Tenant]:
    """The GitHub deriver: which of Doug's installations this user reaches,
    and which repositories through each.

    THE app_id FILTER IS LOAD-BEARING. GET /user/installations answers for
    every GitHub App the caller has installed, not just Doug's — measured, not
    assumed. Without the filter another app's installation id would be stored
    as a Doug tenant, carrying repo ids Doug has no relationship with.

    Which is also why a missing app id raises instead of degrading: filtering
    on nothing would admit those foreign installations, and filtering
    everything out would store an empty scope that reads exactly like "you
    have no tenants" and never recovers on its own.

    Both repository_selection values take the same path. 'all' is not a
    licence to skip the second call — it means every repo the installation
    covers today, and only GitHub can say what that is.
    """
    if not token:
        # No credential is nothing to ask with, not a failure: a user who
        # signed in through a connection that produced no GitHub token has no
        # GitHub entitlement, and that is an answer.
        return []
    app_id = (app_auth.app_id() or "").strip()
    if not app_id:
        raise EntitlementsNotConfigured()
    tenants: list[Tenant] = []
    for installation in _entries("/user/installations", token, "installations"):
        if str(installation.get("app_id")).strip() != app_id:
            continue
        installation_id = installation.get("id")
        if not isinstance(installation_id, int):
            continue
        repos = _entries(
            f"/user/installations/{installation_id}/repositories", token, "repositories"
        )
        repo_ids = {r["id"] for r in repos if isinstance(r.get("id"), int)}
        tenants.append(Tenant(installation_id=installation_id, repo_ids=tuple(sorted(repo_ids))))
    return tenants


# Provider name -> deriver. The name is matched as a substring of the
# lowercased provider, because the name comes from the identity provider and
# WorkOS spells it 'GithubOAuth' in one place and 'github' in another
# (workos_client.github_user_id_for matches the same way). Adding a source
# later is an entry here plus a function, and nothing else in the session
# layer changes — that is what "provider-neutral" has to mean to be worth
# claiming.
_DERIVERS = {"github": _derive_github}


def _deriver_for(provider: str):
    name = (provider or "").strip().lower()
    if not name:
        return None
    for known, deriver in _DERIVERS.items():
        if known in name:
            return deriver
    return None


def derive(provider: str, token: str) -> list[Tenant]:
    """Everything this user is entitled to, as the named provider reports it.

    An unknown provider is an empty answer, never an exception: it becomes
    reachable the moment a second WorkOS connection exists, and a user who
    signed in without GitHub must see nothing rather than a 500. It is logged
    because "no deriver for this name" and "this name drifted" look identical
    from the outside, and only the log tells them apart.
    """
    deriver = _deriver_for(provider)
    if deriver is None:
        print(
            f"doug: no entitlement deriver for provider {provider!r} — deriving no tenants. "
            f"If this is a provider Doug should know, add it to entitlements._DERIVERS.",
            file=sys.stderr,
        )
        return []
    return deriver(token)


def is_stale(derived_at: datetime | None) -> bool:
    """Whether a stored scope is past its ceiling and must be re-derived.

    None is stale: nothing derived is not fresh. A naive timestamp is read as
    UTC, because sqlite hands DateTime(timezone=True) columns back naive
    (store._as_utc's note) and a local-time reading would call an
    eight-hour-old scope fresh for another eight west of Greenwich.
    """
    if derived_at is None:
        return True
    at = derived_at.replace(tzinfo=UTC) if derived_at.tzinfo is None else derived_at
    return datetime.now(UTC) - at >= TTL
