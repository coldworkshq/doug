"""Cloud Run Job entrypoint for outcome-lane reconciliation.

Runs worker.reconcile_all_outcomes() on its own cadence, independent of the
adjudicator's daily drain. Kept as its own Job rather than folded into
doug.outcome_worker: the adjudicator's drain() is deliberately fail-loud (a
systemic defect must turn the Cloud Run execution red — outcome_worker.py's
own comment says so), and reconciliation is deliberately best-effort (one
tenant's GitHub API hiccup must not block every other tenant's catch-up,
same as worker.reconcile_all already is for the review lane). Mixing those
two philosophies in one entrypoint risks a future edit quietly dropping
whichever one wasn't the file's obvious default.

See docs/superpowers/plans/2026-08-12-outcome-lane-reconciliation.md for the
full design rationale.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from . import app_auth, worker


@dataclass(frozen=True)
class ReconcileSummary:
    windows_enqueued: int = 0


def run() -> ReconcileSummary:
    if not app_auth.enabled():
        raise RuntimeError(
            "DOUG_GITHUB_APP_ID and GITHUB_APP_PRIVATE_KEY must be configured "
            "before reconciling"
        )
    return ReconcileSummary(windows_enqueued=worker.reconcile_all_outcomes())


def main() -> None:
    summary = run()
    print(json.dumps(asdict(summary), sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
