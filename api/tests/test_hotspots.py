from magpie.backtest.harvest import HarvestedPR
from magpie.backtest.hotspots import learn_hotspot_segments


def _pr(number: int, files: list[str]) -> HarvestedPR:
    return HarvestedPR.model_validate(
        dict(
            number=number,
            title="t",
            body="",
            author="dev",
            author_is_bot=False,
            additions=10,
            deletions=2,
            files=files,
            created_at="2026-01-01 10:00:00+00:00",
            merged_at="2026-01-02 10:00:00+00:00",
            approvals=1,
            first_approval_at="2026-01-01 11:00:00+00:00",
        )
    )


def test_learn_hotspots_prefers_elevated_segments():
    # 10 PRs; 2 defects both touch preprod; noise touches api generically.
    prs = [
        _pr(1, ["src/sentry/preprod/api.py"]),
        _pr(2, ["src/sentry/preprod/tasks.py"]),
        _pr(3, ["src/sentry/api/endpoints/foo.py"]),
        _pr(4, ["src/sentry/api/endpoints/bar.py"]),
        _pr(5, ["src/sentry/api/endpoints/baz.py"]),
        _pr(6, ["README.md"]),
        _pr(7, ["docs/x.md"]),
        _pr(8, ["static/app/views/x.tsx"]),
        _pr(9, ["static/app/views/y.tsx"]),
        _pr(10, ["static/app/views/z.tsx"]),
    ]
    learned = learn_hotspot_segments(prs, {1, 2}, min_defects=2, min_lift=2.5)
    assert "preprod" in learned
    assert "api" not in learned  # stopped / too generic
