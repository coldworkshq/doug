from doug.backtest.harvest import HarvestedPR
from doug.backtest.hotspots import learn_hotspot_segments, rolling_window


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


def _dated(number: int, merged: str, files: list[str]) -> HarvestedPR:
    pr = _pr(number, files)
    pr.merged_at = merged
    return pr


def _window(prs, labels, as_of, **kw):
    w, d = rolling_window(prs, labels, as_of, **kw)
    return {p.number for p in w}, d


def test_window_stops_once_it_holds_enough_defects():
    prs = [_dated(n, f"2026-03-{n:02d}T00:00:00+00:00", ["a/b.py"]) for n in range(1, 21)]
    labels = {n: f"2026-03-{n:02d}T12:00:00+00:00" for n in (2, 5, 9, 14, 18)}
    seen, defects = _window(prs, labels, "2026-04-01T00:00:00+00:00", min_defects=2, max_days=365)
    # Walking back from April: 18 and 14 are the two most recent defects, and
    # the window stops there rather than dragging in all of March.
    assert defects == {14, 18}
    assert min(seen) == 14


def test_window_ignores_reverts_that_had_not_landed_yet():
    prs = [_dated(n, f"2026-03-{n:02d}T00:00:00+00:00", ["a/b.py"]) for n in range(1, 11)]
    # PR 3 merged in March but was not reverted until May: on 2026-04-01 a live
    # Doug has no way to know it was bad, so it must not train on it.
    labels = {3: "2026-05-01T00:00:00+00:00", 7: "2026-03-20T00:00:00+00:00"}
    _, defects = _window(prs, labels, "2026-04-01T00:00:00+00:00", min_defects=5, max_days=365)
    assert defects == {7}


def test_window_never_reaches_past_the_day_cap():
    prs = [_dated(n, f"2026-01-{n:02d}T00:00:00+00:00", ["a/b.py"]) for n in range(1, 11)]
    labels = {1: "2026-01-02T00:00:00+00:00"}
    # Only one defect exists and min_defects wants three, but the cap wins.
    seen, defects = _window(prs, labels, "2026-03-01T00:00:00+00:00", min_defects=3, max_days=30)
    assert seen == set()
    assert defects == set()


def test_window_excludes_prs_merged_after_the_cutoff():
    prs = [_dated(n, f"2026-03-{n:02d}T00:00:00+00:00", ["a/b.py"]) for n in range(1, 11)]
    labels = {2: "2026-03-03T00:00:00+00:00"}
    seen, _ = _window(prs, labels, "2026-03-05T00:00:00+00:00", min_defects=1, max_days=365)
    assert max(seen) < 5
