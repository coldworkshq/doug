# Task 6g report: caller-CWD-independent deploy script

Status: complete

## Delivered

- `api/deploy/gcp.sh` now derives its directory from `BASH_SOURCE`, resolves
  the repository root, and changes to `api/` before any relative deployment
  path or external command is used.
- The preregistration path is repository-root based. A missing or unreadable
  document now reports `cannot read publication pre-registration`; a readable
  DRAFT document retains the existing `not LOCKED` refusal.
- Caller-level fake-boundary tests execute the original script by absolute path
  from both repository root and an unrelated directory. They prove the locked
  document hash reaches the adjudicator and every full-deploy fake `gcloud`
  call observes `api/` as its CWD. The copied-script DRAFT fixtures remain.

## TDD and verification

Before the script change, the three new boundary tests failed as expected:
absolute invocations reported the old caller-relative missing-file error and
the generic `not LOCKED` message; the missing-document fixture lacked the new
read error. After the minimal script change, the focused regression run passed:

```sh
PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/test_deploy_gcp.py -q -p no:cacheprovider -k 'resolves_the_locked_preregistration or normalizes_to_api or missing_preregistration'
# 3 passed, 16 deselected
```

Final checks from `api/`:

```sh
PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/test_deploy_gcp.py -q -p no:cacheprovider
# 19 passed
bash -n deploy/gcp.sh
uv run ruff check tests/test_deploy_gcp.py --no-cache
git diff --check
```

The syntax and diff checks were silent; Ruff reported `All checks passed!`.

## Boundaries and concerns

Only `api/deploy/gcp.sh`, `api/tests/test_deploy_gcp.py`, and this required
task report are included. No real `gcloud` or `curl` call ran: all exercised
external boundaries were temporary fake binaries. No production, ledger, plan,
PR, push, or remote state was changed. Concerns: none.
