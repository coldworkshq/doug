from doug.models import Band, PRMetadata
from doug.scoring import score


def _pr(**kw) -> PRMetadata:
    base = dict(number=1, title="t", author="dev")
    base.update(kw)
    return PRMetadata.model_validate(base)


def test_trivial_doc_change_clears():
    v = score(_pr(files=["README.md"], additions=3, deletions=1), threshold=0.62)
    assert v.band is Band.CLEARED
    assert v.reasons == []


def test_boundary_plus_migration_flags():
    v = score(
        _pr(
            files=["auth/session.go", "migrations/0042.sql"],
            additions=500,
            deletions=100,
            approvals=1,
            approval_latency_s=200,
        ),
        threshold=0.62,
    )
    assert v.band is Band.FLAGGED
    rules = {r.rule for r in v.reasons}
    assert "boundary-plus-migration" in rules
    assert "sensitive-path" in rules


def test_dep_bump_without_tests_scores_but_clears_alone():
    v = score(_pr(files=["package.json", "package-lock.json"]), threshold=0.62)
    assert {r.rule for r in v.reasons} == {"dep-change-no-test-delta"}
    assert v.band is Band.CLEARED


def test_eslint_dep_bump_does_not_fire_dep_rule():
    v = score(
        _pr(
            title="build(deps): bump eslint from 8 to 9",
            files=["package.json", "package-lock.json"],
        ),
        threshold=0.62,
    )
    assert "dep-change-no-test-delta" not in {r.rule for r in v.reasons}


def test_hotspot_and_config_flag_rules():
    v = score(
        _pr(
            files=[
                "src/sentry/preprod/snapshots/tasks.py",
                "src/sentry/options/defaults.py",
            ],
            additions=40,
            deletions=5,
        ),
        threshold=0.62,
    )
    rules = {r.rule for r in v.reasons}
    assert "hotspot-path" in rules
    assert "config-flag" in rules


def test_size_alone_never_flags():
    # 10k-line diff with tests, slow multi-reviewer approval: no rule fires.
    v = score(
        _pr(
            files=["src/big.py", "tests/test_big.py"],
            additions=9000,
            deletions=1000,
            approvals=2,
            approval_latency_s=86400,
        ),
        threshold=0.62,
    )
    assert v.reasons == []
    assert v.band is Band.CLEARED


def test_threshold_is_respected():
    pr = _pr(files=["package.json"], additions=400)
    strict = score(pr, threshold=0.10)
    lax = score(pr, threshold=0.90)
    assert strict.band is Band.FLAGGED
    assert lax.band is Band.CLEARED


def test_bot_authored_non_dep_fires_agent_rule():
    v = score(
        _pr(author="bot[bot]", files=["src/x.py"], additions=10, deletions=2),
        threshold=0.62,
    )
    assert "agent-authored" in {r.rule for r in v.reasons}


def test_bot_dep_bump_skips_agent_rule():
    v = score(
        _pr(
            author="dependabot[bot]",
            files=["package.json", "package-lock.json"],
        ),
        threshold=0.62,
    )
    assert "agent-authored" not in {r.rule for r in v.reasons}


def test_bot_mixed_code_and_lockfile_keeps_agent_rule():
    v = score(
        _pr(
            author="bot[bot]",
            files=["src/auth/session.py", "package.json"],
            additions=40,
            deletions=5,
        ),
        threshold=0.62,
    )
    assert "agent-authored" in {r.rule for r in v.reasons}
