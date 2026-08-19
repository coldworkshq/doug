"""The sticky PR comment — one framed mirror of the check run.

Three properties are load-bearing and each is written here as a defect:

  * The middle of the body is the check run's summary BYTE-FOR-BYTE. That
    identity is the whole claim of ADR-0014; a frame that re-wraps or
    re-sanitises the summary breaks it silently.
  * A comment a human wrote is never matched and never written. With
    `pull_requests: write` the App can edit ANY comment on the PR, and
    anyone can post one starting with the marker on a public repo, so a
    marker-only match is a slot hijack under Doug's name.
  * "No comment exists" is concluded only after a listing that COMPLETED.
    The wrong default there is a duplicate comment — and a fresh
    notification — on every push for as long as the fault lasts.
"""

from types import SimpleNamespace

import httpx
import pytest
from githubkit.exception import RequestError, RequestFailed

from doug import check_run, pr_comment, store

APP_ID = "4450932"
BODY = "<!-- doug:verdict head=bbbbbbbbbb seq=5 -->\n\nthe rendered body"
KEY = dict(installation_id=101, github_repo_id=11, seq=5)
PR = 7


def _db(tmp_path, monkeypatch) -> str:
    url = f"sqlite:///{tmp_path}/doug.db"
    monkeypatch.setenv("DATABASE_URL", url)
    return url


def _failed(status: int) -> RequestFailed:
    """githubkit's RequestFailed reads only raw_request/raw_response off the
    Response it is handed, and exposes the object as `.response`."""
    request = httpx.Request("POST", "https://api.github.com/")
    response = httpx.Response(status, request=request)
    return RequestFailed(
        SimpleNamespace(status_code=status, raw_request=request, raw_response=response)
    )


def _comment(cid: int, body, *, app_id=APP_ID, user_type="Bot", login="doug[bot]"):
    app = None if app_id is None else SimpleNamespace(id=int(app_id))
    return SimpleNamespace(
        id=cid,
        body=body,
        performed_via_github_app=app,
        user=SimpleNamespace(type=user_type, login=login),
    )


def _marked(cid: int, *, seq: int, head: str = "a" * 40, **kw):
    body = f"<!-- doug:verdict head={head} seq={seq} -->\n\n**Cleared**\n\n- none"
    return _comment(cid, body, **kw)


class _Issues:
    """rest.issues, recording every call so a test can assert what did NOT
    happen (no create after a failed listing; no write to a human's id)."""

    def __init__(
        self,
        pages=None,
        *,
        list_error=None,
        create_error=None,
        update_errors=None,
        full_pages=False,
    ):
        self._pages = [[]] if pages is None else pages
        self._list_error = list_error
        self._create_error = create_error
        self._update_errors = update_errors or {}
        self._full_pages = full_pages
        self._next_id = 900
        self.calls: list[tuple] = []

    def list_comments(self, *, owner, repo, issue_number, per_page, page):
        self.calls.append(("list", page))
        if self._list_error is not None:
            raise self._list_error
        if self._full_pages:
            batch = [
                _comment(page * 1000 + i, "a human said hi", app_id=None)
                for i in range(per_page)
            ]
        else:
            batch = self._pages[page - 1] if page - 1 < len(self._pages) else []
        return SimpleNamespace(parsed_data=batch)

    def create_comment(self, *, owner, repo, issue_number, body):
        self.calls.append(("create", body))
        if self._create_error is not None:
            raise self._create_error
        self._next_id += 1
        return SimpleNamespace(parsed_data=SimpleNamespace(id=self._next_id))

    def update_comment(self, *, owner, repo, comment_id, body):
        self.calls.append(("update", comment_id))
        error = self._update_errors.get(comment_id)
        if error is not None:
            raise error
        return SimpleNamespace(parsed_data=SimpleNamespace(id=comment_id))


class _Pulls:
    def __init__(self, base_repo_id=11, *, error=None, base=True):
        self._base_repo_id = base_repo_id
        self._error = error
        self._base = base
        self.calls: list[tuple] = []

    def get(self, *, owner, repo, pull_number):
        self.calls.append(("get", pull_number))
        if self._error is not None:
            raise self._error
        base = SimpleNamespace(repo=SimpleNamespace(id=self._base_repo_id)) if self._base else None
        return SimpleNamespace(parsed_data=SimpleNamespace(base=base))


def _gh(issues=None, pulls=None):
    return SimpleNamespace(
        rest=SimpleNamespace(issues=issues or _Issues(), pulls=pulls or _Pulls())
    )


def _upsert(gh, **kw):
    return pr_comment.upsert(gh, "o", "r", PR, BODY, **{**KEY, **kw})


# --- render / receipt_url -------------------------------------------------


def test_render_frames_the_summary_verbatim_with_pinned_joins():
    body = pr_comment.render(
        "**T**\n\n- none",
        head_sha="a" * 40,
        seq=7,
        receipt_url="https://hq/dashboard/pr/3?repo=o%2Fr",
    )
    lines = body.split("\n")
    assert lines[0] == f"<!-- doug:verdict head={'a' * 40} seq=7 -->"
    assert lines[1] == ""
    assert lines[2].startswith("_The `Doug` check run for aaaaaaa, repeated here in full.")
    assert lines[3] == ""
    # The summary can end on a list item; one newline before `---` is a GFM
    # lazy continuation and two is the rule (check_run._footer, same defect).
    assert "\n\n- none\n\n---\n" in body
    assert "**T**\n\n- none" in body
    receipt = "[full receipt on Doug HQ](https://hq/dashboard/pr/3?repo=o%2Fr)"
    assert f"{receipt} — sign-in required" in body
    assert "/docs/what-doug-gets-wrong" in body


def test_render_without_a_web_url_omits_both_links_and_still_renders():
    body = pr_comment.render("**T**\n\n- none", head_sha="b" * 40, seq=1, receipt_url=None)
    assert body.startswith(f"<!-- doug:verdict head={'b' * 40} seq=1 -->\n\n")
    assert "**T**\n\n- none\n\n---\n" in body
    assert "](" not in body.split("\n---\n")[1]
    assert "Doug HQ" not in body
    assert "what-doug-gets-wrong" not in body


def test_frame_plus_summary_limit_fits_githubs_comment_cap():
    assert check_run.SUMMARY_LIMIT + pr_comment.FRAME_MAX <= 65_536


def test_the_frame_of_a_worst_case_url_stays_inside_frame_max(monkeypatch):
    """FRAME_MAX is only an honest bound if a real frame respects it — the
    constant-vs-constant assertion above cannot fail on its own. Longest
    plausible inputs: GitHub's own owner (39) and repo (100) name caps."""
    monkeypatch.setenv("DOUG_WEB_URL", "https://doug-web-000000000000.us-central1.run.app/")
    url = pr_comment.receipt_url("o" * 39, "r" * 100, 99_999_999)
    assert url is not None
    frame = pr_comment.render("", head_sha="c" * 40, seq=2_147_483_647, receipt_url=url)
    assert len(frame) <= pr_comment.FRAME_MAX


def test_receipt_url_encodes_the_repo_and_is_none_when_env_empty(monkeypatch):
    monkeypatch.setenv("DOUG_WEB_URL", "")
    assert pr_comment.receipt_url("o", "r", 3) is None
    monkeypatch.setenv("DOUG_WEB_URL", "https://hq")
    assert pr_comment.receipt_url("o", "r", 3) == "https://hq/dashboard/pr/3?repo=o%2Fr"


def test_receipt_url_warns_once_per_process_when_the_web_url_is_unset(monkeypatch, capsys):
    monkeypatch.setattr(pr_comment, "_WARNED_NO_WEB_URL", False)
    monkeypatch.delenv("DOUG_WEB_URL", raising=False)
    assert pr_comment.receipt_url("o", "r", 3) is None
    assert pr_comment.receipt_url("o", "r", 4) is None
    assert capsys.readouterr().err.count("DOUG_WEB_URL") == 1


# --- upsert ---------------------------------------------------------------


def test_upsert_updates_by_stored_id_and_never_lists(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_GITHUB_APP_ID", APP_ID)
    store.claim_pr_comment(101, 11, PR)
    store.set_pr_comment_id(101, 11, PR, 111)
    issues = _Issues()
    assert _upsert(_gh(issues)) == "updated"
    assert issues.calls == [("update", 111)]


def test_upsert_on_a_404_for_the_stored_id_forgets_then_lists_then_creates(tmp_path, monkeypatch):
    """Someone deleted Doug's comment. Re-creating is correct; the claim row
    must be released first or the create is never reached."""
    _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_GITHUB_APP_ID", APP_ID)
    store.claim_pr_comment(101, 11, PR)
    store.set_pr_comment_id(101, 11, PR, 111)
    issues = _Issues(update_errors={111: _failed(404)})
    assert _upsert(_gh(issues)) == "created"
    assert [c[0] for c in issues.calls] == ["update", "list", "create"]
    assert store.pr_comment_id(101, 11, PR) == 901


def test_upsert_does_not_re_list_when_the_stored_id_fails_for_any_other_reason(
    tmp_path, monkeypatch
):
    """Only a 404 means "it is gone". Treating every failure as one would
    forget a live claim and list-then-create a second comment."""
    _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_GITHUB_APP_ID", APP_ID)
    store.claim_pr_comment(101, 11, PR)
    store.set_pr_comment_id(101, 11, PR, 111)
    issues = _Issues(update_errors={111: _failed(403)})
    assert _upsert(_gh(issues)) == "denied:403"
    assert [c[0] for c in issues.calls] == ["update"]
    assert store.pr_comment_id(101, 11, PR) == 111


def test_upsert_never_matches_a_human_authored_marked_comment_and_creates_its_own(
    tmp_path, monkeypatch
):
    """Anyone can post a comment starting with the marker on a public repo,
    and the App has write on every comment. Authorship is the only guard."""
    _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_GITHUB_APP_ID", APP_ID)
    human = _marked(5, seq=99, app_id=None, user_type="User", login="mallory")
    other_app = _marked(6, seq=99, app_id="999")
    issues = _Issues(pages=[[human, other_app]])
    assert _upsert(_gh(issues)) == "created"
    assert ("update", 5) not in issues.calls
    assert ("update", 6) not in issues.calls
    assert ("create", BODY) in issues.calls


def test_upsert_never_matches_anything_when_this_deployment_has_no_app_id(
    tmp_path, monkeypatch
):
    """No app id means no way to prove authorship, so nothing matches — the
    open failure is a duplicate, not an overwrite of someone else's text."""
    _db(tmp_path, monkeypatch)
    monkeypatch.delenv("DOUG_GITHUB_APP_ID", raising=False)
    issues = _Issues(pages=[[_marked(5, seq=1), _comment(6, "x", app_id=None)]])
    assert _upsert(_gh(issues)) == "created"
    assert ("update", 5) not in issues.calls


def test_upsert_skips_when_the_existing_seq_is_newer(tmp_path, monkeypatch):
    """Two drainers are the deployed configuration; an older job finishing
    last must not regress the verdict a newer one already published."""
    _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_GITHUB_APP_ID", APP_ID)
    issues = _Issues(pages=[[_marked(42, seq=9)]])
    assert _upsert(_gh(issues), seq=5) == "skipped-stale"
    assert [c[0] for c in issues.calls] == ["list"]
    # The id is still learned: the next job must not have to list again.
    assert store.pr_comment_id(101, 11, PR) == 42


def test_upsert_updates_when_the_existing_seq_is_older_or_equal(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_GITHUB_APP_ID", APP_ID)
    issues = _Issues(pages=[[_marked(42, seq=4)]])
    assert _upsert(_gh(issues), seq=5) == "updated"
    assert ("update", 42) in issues.calls
    assert store.pr_comment_id(101, 11, PR) == 42


def test_upsert_on_listing_failure_returns_failed_and_never_creates(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_GITHUB_APP_ID", APP_ID)
    issues = _Issues(list_error=_failed(500))
    assert _upsert(_gh(issues)) == "failed:500"
    assert [c[0] for c in issues.calls] == ["list"]
    assert store.pr_comment_id(101, 11, PR) is None


def test_upsert_on_page_bound_returns_failed_and_never_creates(tmp_path, monkeypatch):
    """A PR with more comments than the bound is indistinguishable from a
    broken listing, and both must fail rather than post a second comment."""
    _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_GITHUB_APP_ID", APP_ID)
    monkeypatch.setattr(pr_comment, "_PER_PAGE", 2)
    issues = _Issues(full_pages=True)
    assert _upsert(_gh(issues)) == "failed:page-bound"
    assert [c[0] for c in issues.calls] == ["list"] * pr_comment._PAGE_BOUND
    assert store.pr_comment_id(101, 11, PR) is None


def test_upsert_claim_lost_updates_instead_of_creating(tmp_path, monkeypatch):
    """The other drainer won the claim and wrote its comment id between our
    listing and our claim. Re-read it and update; two creates is the defect."""
    _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_GITHUB_APP_ID", APP_ID)
    store.claim_pr_comment(101, 11, PR)  # row exists, comment_id still NULL
    reads = iter([None, 88])
    monkeypatch.setattr(pr_comment.store, "pr_comment_id", lambda *a: next(reads))
    issues = _Issues()
    assert _upsert(_gh(issues)) == "updated"
    assert [c[0] for c in issues.calls] == ["list", "update"]
    assert ("update", 88) in issues.calls


def test_upsert_403_is_denied_and_does_not_raise(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_GITHUB_APP_ID", APP_ID)
    issues = _Issues(create_error=_failed(403))
    assert _upsert(_gh(issues)) == "denied:403"


def test_upsert_tolerates_a_comment_with_unset_body(tmp_path, monkeypatch):
    """IssueComment.body is Missing[str]: absent and None both happen."""
    _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_GITHUB_APP_ID", APP_ID)
    bodyless = SimpleNamespace(id=3, performed_via_github_app=SimpleNamespace(id=int(APP_ID)))
    issues = _Issues(pages=[[bodyless, _comment(4, None)]])
    assert _upsert(_gh(issues)) == "created"
    assert ("create", BODY) in issues.calls


def test_upsert_network_error_is_failed_net(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_GITHUB_APP_ID", APP_ID)
    issues = _Issues(list_error=RequestError(httpx.ConnectError("no route")))
    assert _upsert(_gh(issues)) == "failed:net"
    assert [c[0] for c in issues.calls] == ["list"]


def test_upsert_lets_a_programming_error_propagate(tmp_path, monkeypatch):
    """upsert has real logic; a blanket except would report its own bugs as
    `failed` on 100% of PRs with nothing red anywhere."""
    _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_GITHUB_APP_ID", APP_ID)
    issues = _Issues(create_error=TypeError("unexpected keyword argument"))
    with pytest.raises(TypeError):
        _upsert(_gh(issues))


# --- target_matches / allowed --------------------------------------------


def test_target_matches_compares_base_repo_id():
    """repo_full_name is display-only and goes stale on rename; a comment
    needs only the PR number to exist, so repo A's findings can land on
    repo B's PR inside the same installation."""
    assert pr_comment.target_matches(_gh(pulls=_Pulls(11)), "o", "r", PR, 11) is True
    assert pr_comment.target_matches(_gh(pulls=_Pulls(12)), "o", "r", PR, 11) is False
    assert pr_comment.target_matches(_gh(pulls=_Pulls(base=False)), "o", "r", PR, 11) is False
    assert (
        pr_comment.target_matches(_gh(pulls=_Pulls(error=_failed(404))), "o", "r", PR, 11) is False
    )
    assert (
        pr_comment.target_matches(
            _gh(pulls=_Pulls(error=RequestError(httpx.ConnectError("x")))), "o", "r", PR, 11
        )
        is False
    )


def test_allowed_reads_the_allowlist_env_like_intent(monkeypatch):
    """An unset allowlist enables nobody, not everybody (intent.enabled_for)."""
    monkeypatch.delenv(pr_comment.ALLOWLIST_ENV, raising=False)
    assert pr_comment.allowed(101) is False
    monkeypatch.setenv(pr_comment.ALLOWLIST_ENV, "")
    assert pr_comment.allowed(101) is False
    monkeypatch.setenv(pr_comment.ALLOWLIST_ENV, " 101 , 202 ")
    assert pr_comment.allowed(101) is True
    assert pr_comment.allowed(202) is True
    assert pr_comment.allowed(303) is False
