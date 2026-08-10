"""Tests for entitlement derivation and its storage.

No test in this file performs network I/O. `entitlements._send` is the
module's ONE network boundary and every test here replaces it with a local
fake — the same posture test_workos_client.py takes toward WorkOS and
test_session_auth.py takes toward JWKS. The fake answers with real
`httpx.Response` objects and pages them itself, so the paging loop under test
is the one production runs rather than a hand-written page sequence.

The store half runs against a real sqlite file (tmp_path), because the
properties that matter here — the unique constraint, and re-derivation
replacing rather than accumulating — are properties of the schema, not of
the Python that writes it.
"""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import inspect, select

from doug import entitlements, store

# Doug's own GitHub App id, as api/deploy/gcp.sh sets it in both services.
# GET /user/installations answers for EVERY app the caller has installed, so
# this value is the filter that keeps another app's installation from
# becoming a Doug tenant.
DOUG_APP_ID = "4450932"


class _FakeGitHub:
    """Stands in for entitlements._send.

    Holds the FULL entry list per path and slices it into pages itself, so a
    test says "this installation has 150 repositories" and the module's own
    paging is what has to walk them. Records every (path, page) and every
    header dict, so "the token was sent to GitHub and nowhere else" is an
    observed fact rather than an assumption about a stub.
    """

    def __init__(self, paths: dict[str, list[dict]] | None = None, status: dict | None = None):
        self.paths = paths or {}
        self.status = status or {}
        self.calls: list[tuple[str, int]] = []
        self.headers: list[dict] = []

    def __call__(self, url, *, headers, params):
        assert url.startswith(entitlements.GITHUB_API), url
        path = url[len(entitlements.GITHUB_API) :]
        self.calls.append((path, params["page"]))
        self.headers.append(headers)
        if path in self.status:
            return httpx.Response(self.status[path], json={"message": "no"})
        if path not in self.paths:
            raise AssertionError(f"unexpected GitHub call: {path}")
        entries = self.paths[path]
        key = "repositories" if path.endswith("/repositories") else "installations"
        page = params["page"]
        per_page = params["per_page"]
        chunk = entries[(page - 1) * per_page : page * per_page]
        return httpx.Response(200, json={"total_count": len(entries), key: chunk})

    def visited(self) -> list[str]:
        return [path for path, _ in self.calls]


def _installation(installation_id: int, *, app_id: str = DOUG_APP_ID, selection="selected"):
    return {
        "id": installation_id,
        "app_id": int(app_id),
        "repository_selection": selection,
        "account": {"login": "drewjst"},
    }


def _repo(repo_id: int) -> dict:
    return {"id": repo_id, "full_name": f"drewjst/repo{repo_id}"}


def _github(monkeypatch, paths=None, status=None) -> _FakeGitHub:
    fake = _FakeGitHub(paths, status)
    monkeypatch.setattr(entitlements, "_send", fake)
    monkeypatch.setenv("DOUG_GITHUB_APP_ID", DOUG_APP_ID)
    return fake


def _db(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/doug.db")


class _AnyTime:
    """Equality helper: derived_at is a real clock reading, so a stored row is
    compared on everything except its instant."""

    def __eq__(self, other):
        return isinstance(other, datetime)

    def __repr__(self):
        return "<any datetime>"


ANY_TIME = _AnyTime()


def test_selected_and_all_repository_selection_both_resolve_to_explicit_repo_ids(monkeypatch):
    """Measured in production: drewjst is 'selected', lemahq is 'all'. Never
    assume 'all'.

    Both are derived the same way — by asking GitHub which repositories THIS
    user reaches through THIS installation — because 'all' is not a licence
    to skip the call: it means every repo the installation covers *today*,
    which is a list only GitHub can produce. A session's scope is never
    installation-wide (tenancy.SessionContext), so both selections have to
    end at concrete ids.
    """
    fake = _github(
        monkeypatch,
        {
            "/user/installations": [
                _installation(1001, selection="selected"),
                _installation(1002, selection="all"),
            ],
            "/user/installations/1001/repositories": [_repo(11), _repo(12)],
            "/user/installations/1002/repositories": [_repo(21), _repo(22), _repo(23)],
        },
    )

    assert entitlements.derive("github", "ghu_token") == [
        entitlements.Tenant(installation_id=1001, repo_ids=(11, 12)),
        entitlements.Tenant(installation_id=1002, repo_ids=(21, 22, 23)),
    ]
    # The 'all' installation was asked too, not shortcut.
    assert "/user/installations/1002/repositories" in fake.visited()


def test_derivation_with_no_github_identity_yields_no_tenants_and_does_not_raise(monkeypatch):
    """Reachable the moment a second WorkOS connection exists. A user who
    signed in without GitHub sees nothing; they must not get a 500.

    Three shapes of "no GitHub identity", all of which degrade rather than
    raise: a provider Doug has no deriver for, a provider that produced no
    token at all, and a GitHub token whose account has never installed Doug.
    """
    fake = _github(monkeypatch, {"/user/installations": []})

    assert entitlements.derive("GoogleOAuth", "ya29.token") == []
    assert entitlements.derive("", "") == []
    assert fake.calls == [], "an unknown provider must not spend a GitHub call"

    assert entitlements.derive("github", "") == []
    assert fake.calls == [], "no token is nothing to ask with"

    assert entitlements.derive("github", "ghu_token") == []
    assert fake.visited() == ["/user/installations"]


def test_only_dougs_own_installations_become_tenants(monkeypatch):
    """GET /user/installations answers for every GitHub App the caller has
    installed. Without the app_id filter, someone else's app installation
    would become a Doug tenant — an installation id Doug never saw, carrying
    repo ids Doug has no relationship with."""
    fake = _github(
        monkeypatch,
        {
            "/user/installations": [
                _installation(1001),
                _installation(2002, app_id="99999"),  # somebody else's app
            ],
            "/user/installations/1001/repositories": [_repo(11)],
        },
    )

    assert entitlements.derive("github", "ghu_token") == [
        entitlements.Tenant(installation_id=1001, repo_ids=(11,))
    ]
    # Not merely absent from the result — never even asked about, so a
    # foreign installation costs the caller's quota nothing.
    assert "/user/installations/2002/repositories" not in fake.visited()


def test_derivation_pages_through_every_installation_and_repository(monkeypatch):
    """GitHub caps a page at 100. A single-page read would silently truncate
    a large tenant's scope to its first 100 repos — and a scope that is
    quietly short is worse than one that fails, because the dashboard renders
    it as though it were complete."""
    repos = [_repo(i) for i in range(1, 251)]
    fake = _github(
        monkeypatch,
        {
            "/user/installations": [_installation(1001)],
            "/user/installations/1001/repositories": repos,
        },
    )

    [tenant] = entitlements.derive("github", "ghu_token")
    assert tenant.repo_ids == tuple(range(1, 251))
    # 3 pages of repositories (100 + 100 + 50), not 1.
    assert [
        page for path, page in fake.calls if path.endswith("/repositories")
    ] == [1, 2, 3]


def test_an_unknown_provider_says_so_rather_than_only_yielding_nothing(monkeypatch, capsys):
    """Dispatch is by name, and the name comes from the identity provider —
    'GithubOAuth' today, whatever WorkOS calls the next connection later. A
    name Doug has no deriver for is a legitimate answer of "no tenants", and
    also the exact shape a naming drift would take, so it is logged: one grep
    tells an operator which it was instead of a silently empty dashboard."""
    _github(monkeypatch, {})

    assert entitlements.derive("MicrosoftOAuth", "tok") == []
    err = capsys.readouterr().err
    assert "MicrosoftOAuth" in err
    assert "tok" not in err

    # And a provider Doug DOES know is not logged as unknown — otherwise this
    # test would pass on a module that logged every derivation.
    _github(monkeypatch, {"/user/installations": []})
    assert entitlements.derive("GithubOAuth", "ghu_token") == []
    assert "GithubOAuth" not in capsys.readouterr().err


def test_a_missing_app_id_refuses_rather_than_deriving_an_empty_scope(monkeypatch):
    """DOUG_GITHUB_APP_ID is what tells Doug's installations from every other
    app's. Without it there is no safe answer: filtering on nothing would
    hand the caller foreign installations, and filtering everything out would
    store an empty scope that looks exactly like "you have no tenants" and
    never recovers. A named 503 is the honest third option — api.py:391's
    idiom, same as SessionAuthNotConfigured."""
    fake = _github(monkeypatch, {"/user/installations": [_installation(1001)]})
    monkeypatch.delenv("DOUG_GITHUB_APP_ID", raising=False)

    with pytest.raises(entitlements.EntitlementsNotConfigured):
        entitlements.derive("github", "ghu_token")
    assert fake.calls == [], "nothing is asked before the deployment check"

    # Configured, the same call derives — so the refusal above is the missing
    # id, not a broken deriver.
    monkeypatch.setenv("DOUG_GITHUB_APP_ID", DOUG_APP_ID)
    monkeypatch.setattr(
        entitlements,
        "_send",
        _FakeGitHub(
            {
                "/user/installations": [_installation(1001)],
                "/user/installations/1001/repositories": [_repo(11)],
            }
        ),
    )
    assert entitlements.derive("github", "ghu_token") == [
        entitlements.Tenant(installation_id=1001, repo_ids=(11,))
    ]


def test_a_rejected_token_and_an_outage_are_different_failures(monkeypatch):
    """Neither may be read as "this user is entitled to nothing" — that
    answer gets STORED, and storing it would erase a real tenant's scope on
    the strength of an expired credential or somebody else's incident.

    They are told apart because the caller can act on one of them: a rejected
    token means sign in again, an outage means try later.
    """
    _github(monkeypatch, {}, status={"/user/installations": 401})
    with pytest.raises(entitlements.ProviderTokenRejected):
        entitlements.derive("github", "ghu_expired")

    _github(monkeypatch, {}, status={"/user/installations": 500})
    with pytest.raises(entitlements.ProviderError):
        entitlements.derive("github", "ghu_token")

    def _down(url, *, headers, params):
        raise httpx.ConnectError("github: connection refused")

    monkeypatch.setattr(entitlements, "_send", _down)
    with pytest.raises(entitlements.ProviderError):
        entitlements.derive("github", "ghu_token")


def test_the_provider_token_never_reaches_a_log_line_or_an_exception(monkeypatch, capsys):
    """The unit-level half of the no-credential-at-rest rule (the endpoint's
    half is in test_api.py). The token rides in one header and nowhere else —
    not in the ProviderError a caller may log, and not on stderr."""
    fake = _github(monkeypatch, {}, status={"/user/installations": 500})

    with pytest.raises(entitlements.ProviderError) as exc:
        entitlements.derive("github", "ghu_do_not_leak_me")

    # It genuinely travelled — otherwise "absent everywhere" would pass on a
    # module that never sent it at all.
    assert fake.headers[0]["Authorization"] == "Bearer ghu_do_not_leak_me"
    assert "ghu_do_not_leak_me" not in str(exc.value)
    assert "ghu_do_not_leak_me" not in capsys.readouterr().err


def test_scope_older_than_the_ttl_is_stale():
    """WORKOS_COOKIE_MAX_AGE defaults to ~400 days, so the cookie cannot be
    the ceiling — a scope bounded by session lifetime would be a scope that
    is never re-derived. 8h matches the measured GitHub token TTL, so this
    costs nothing in freshness against having kept the token."""
    now = datetime.now(UTC)
    assert entitlements.TTL == timedelta(hours=8)

    assert entitlements.is_stale(now - timedelta(hours=9))
    assert not entitlements.is_stale(now - timedelta(hours=7))
    assert entitlements.is_stale(None), "nothing derived is not fresh"

    # sqlite hands a DateTime(timezone=True) column back naive (store._as_utc's
    # note). Read as UTC, or a machine west of Greenwich would call an
    # eight-hour-old scope fresh for another eight.
    assert not entitlements.is_stale((now - timedelta(hours=7)).replace(tzinfo=None))
    assert entitlements.is_stale((now - timedelta(hours=9)).replace(tzinfo=None))


def test_entitlement_scope_is_keyed_on_the_workos_user_not_a_github_id(tmp_path, monkeypatch):
    """Login is not necessarily GitHub. Keying storage on a provider's user id
    would have to be migrated the first time a second connection exists — and
    until then it would quietly assume every signed-in user has a GitHub
    identity, which ruling 5 says is already false in principle.

    The GitHub id is not merely unused as a key: it is not stored at all, so
    there is no column for a later reader to start trusting.
    """
    _db(tmp_path, monkeypatch)
    store.replace_session_entitlements("user_01ABC", [(1001, [11, 12])])

    assert store.session_entitlements_for("user_01ABC") == [
        {"installation_id": 1001, "repo_ids": frozenset({11, 12}), "derived_at": ANY_TIME}
    ]
    # The GitHub user id that produced this scope resolves to nothing, because
    # it was never a key here.
    assert store.session_entitlements_for("777") == []

    columns = {c["name"] for c in inspect(store._get_engine()).get_columns("session_entitlements")}
    assert columns == {"id", "workos_user_id", "installation_id", "repo_ids", "derived_at"}


def test_re_deriving_replaces_rather_than_accumulates(tmp_path, monkeypatch):
    """A scope that only ever grew would be a scope that never shrank: the
    repo a tenant removed Doug from would stay readable for as long as the
    user kept signing in. Re-derivation is the whole of what this user may
    see, not a delta."""
    _db(tmp_path, monkeypatch)
    store.replace_session_entitlements("user_01ABC", [(1001, [11, 12]), (1002, [21])])
    store.replace_session_entitlements("user_01ABC", [(1001, [11])])

    assert store.session_entitlements_for("user_01ABC") == [
        {"installation_id": 1001, "repo_ids": frozenset({11}), "derived_at": ANY_TIME}
    ]

    # Another user's rows are untouched by that replacement — the unique
    # constraint is on (workos_user_id, installation_id), not on either alone,
    # so two users may hold the same installation.
    store.replace_session_entitlements("user_02DEF", [(1001, [11, 12])])
    store.replace_session_entitlements("user_01ABC", [(1001, [11])])
    assert store.session_entitlements_for("user_02DEF") == [
        {"installation_id": 1001, "repo_ids": frozenset({11, 12}), "derived_at": ANY_TIME}
    ]


def test_a_derivation_with_no_tenants_clears_what_was_there(tmp_path, monkeypatch):
    """The uninstall case. Deriving nothing is an answer, not a no-op — a
    "nothing changed, so keep the old rows" write would leave a removed
    tenant's scope in place indefinitely."""
    _db(tmp_path, monkeypatch)
    store.replace_session_entitlements("user_01ABC", [(1001, [11])])
    store.replace_session_entitlements("user_01ABC", [])
    assert store.session_entitlements_for("user_01ABC") == []


def test_a_stored_scope_carries_the_instant_it_was_derived(tmp_path, monkeypatch):
    """is_stale has nothing to work from without it, and the whole point of
    storing scope instead of the token is that the scope expires anyway."""
    _db(tmp_path, monkeypatch)
    old = datetime.now(UTC) - timedelta(hours=9)
    store.replace_session_entitlements("user_01ABC", [(1001, [11])], now=old)

    [row] = store.session_entitlements_for("user_01ABC")
    assert entitlements.is_stale(row["derived_at"])

    store.replace_session_entitlements("user_01ABC", [(1001, [11])])
    [fresh] = store.session_entitlements_for("user_01ABC")
    assert not entitlements.is_stale(fresh["derived_at"])


def test_repo_ids_are_stored_as_a_portable_json_array(tmp_path, monkeypatch):
    """TEXT holding JSON, identical on sqlite and Postgres. Nothing queries
    into the array — it is written and read whole — so the portable spelling
    costs nothing and the column means the same thing on both engines."""
    _db(tmp_path, monkeypatch)
    store.replace_session_entitlements("user_01ABC", [(1001, [12, 11, 11])])

    with store._get_engine().connect() as conn:
        raw = conn.execute(select(store.session_entitlements.c.repo_ids)).scalar_one()
    assert json.loads(raw) == [11, 12], "sorted and de-duplicated, not the caller's order"


def test_the_ledger_being_off_is_not_an_error(tmp_path, monkeypatch):
    """Storage is opt-in (store's module docstring). Every other writer here
    is a cheap no-op without DATABASE_URL and this one is no different — a
    local dogfood run must not need a database to sign in."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    store.replace_session_entitlements("user_01ABC", [(1001, [11])])
    assert store.session_entitlements_for("user_01ABC") == []
