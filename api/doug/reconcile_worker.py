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

from . import app_auth, store, worker


@dataclass(frozen=True)
class ReconcileSummary:
    windows_enqueued: int = 0


def run() -> ReconcileSummary:
    if not app_auth.enabled():
        raise RuntimeError(
            "DOUG_GITHUB_APP_ID and GITHUB_APP_PRIVATE_KEY must be configured "
            "before reconciling"
        )
    # Per-tenant failures are best-effort (see the module docstring); a
    # missing ledger is not one of those. Without DATABASE_URL every store
    # call answers as if the world were empty — active_installations() is []
    # and reconcile_all_outcomes() returns 0 — so this Job would report
    # {"windows_enqueued": 0} and go green while healing nothing, which is
    # the exact silent gap it was built to close. Its own secret binding is
    # separate from the API service's, so this can drift on its own.
    # outcome_queue._engine fails the sibling Job loud for the same reason.
    if not store.enabled():
        raise RuntimeError("DATABASE_URL must be configured before reconciling")
    return ReconcileSummary(windows_enqueued=worker.reconcile_all_outcomes())


def main() -> None:
    summary = run()
    print(json.dumps(asdict(summary), sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
