# M3 Deploy Hotfix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the merged M3 deploy create `doug-adjudicator` successfully and tolerate normal service-account visibility propagation.

**Architecture:** Keep the fix inside the existing Bash deployment boundary. Strengthen the fake `gcloud` executable so it reproduces the two production failures, then make the smallest script changes: use an equals-sign Job argument and retry only read-only account visibility checks.

**Tech Stack:** Bash, Google Cloud CLI, Python 3.14, pytest.

## Global Constraints

- The Job must still use the exact immutable image serving `doug-api`.
- The Job command remains `python -m doug.outcome_worker`.
- Service-account creation and IAM mutations are never retried.
- Visibility performs at most ten `describe` calls with one second between failed calls.
- A permanently invisible account fails loudly.
- No production Scheduler or manual Job execution occurs from this branch.

---

### Task 1: Make the Job argument acceptable to real `gcloud`

**Files:**
- Modify: `api/tests/test_deploy_gcp.py`
- Modify: `api/deploy/gcp.sh`

**Interfaces:**
- Consumes: `_run_gcp(tmp_path, "adjudicator") -> list[str]`.
- Produces: a `gcloud run jobs deploy` invocation containing the single argv token `--args=-m,doug.outcome_worker`.

- [ ] **Step 1: Teach the fake CLI to reject the production failure**

Add this loop immediately after the fake records its argv:

```sh
previous=
for argument in "$@"; do
  if [ "$previous" = "--args" ] && [ "${argument#-}" != "$argument" ]; then
    printf '%s\n' 'ERROR: argument --args: expected one argument' >&2
    exit 2
  fi
  previous=$argument
done
```

Change the existing assertion to the independently derived literal:

```python
assert "--args=-m,doug.outcome_worker" in deploy
```

- [ ] **Step 2: Run the executable deployment test and verify RED**

Run:

```bash
cd api
uv run pytest tests/test_deploy_gcp.py::test_adjudicator_deploys_the_live_api_image_with_the_bounded_job_contract -q
```

Expected: FAIL because `_run_gcp` receives exit code 2 and the fake prints `argument --args: expected one argument`.

- [ ] **Step 3: Pass the argument as one unambiguous token**

Change the Job deploy line to:

```bash
--command python --args=-m,doug.outcome_worker \
```

- [ ] **Step 4: Run the test and verify GREEN**

Run the Step 2 command. Expected: one test passes.

- [ ] **Step 5: Commit the CLI fix**

```bash
git add api/deploy/gcp.sh api/tests/test_deploy_gcp.py
git commit -m "fix: pass adjudicator module args to gcloud"
```

---

### Task 2: Bound service-account propagation waits

**Files:**
- Modify: `api/tests/test_deploy_gcp.py`
- Modify: `api/deploy/gcp.sh`

**Interfaces:**
- Produces: `wait_for_service_account(email: str) -> shell status`.
- Extends: `_run_gcp(tmp_path, command, extra_env=None) -> list[str]` for deterministic fake-CLI scenarios.

- [ ] **Step 1: Add a transient-visibility scenario to the fake CLI**

Set a state-file path in `_run_gcp` and permit scenario-specific environment:

```python
def _run_gcp(
    tmp_path: Path, command: str, extra_env: dict[str, str] | None = None
) -> list[str]:
    fake_bin, log = _fake_gcloud(tmp_path)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "GCLOUD_LOG": str(log),
        "GCLOUD_STATE": str(tmp_path / "gcloud.state"),
        "PROJECT": "doug-prod0",
        "REGION": "us-central1",
        **(extra_env or {}),
    }
```

Add this fake behavior before its default `exit 0`:

```sh
if [ "$1 $2 $3" = "iam service-accounts describe" ] \
    && [ "$4" = "${GCLOUD_TRANSIENT_SA:-}" ] \
    && [ ! -f "$GCLOUD_STATE" ]; then
  : > "$GCLOUD_STATE"
  exit 1
fi
```

Add the regression:

```python
def test_adjudicator_setup_waits_for_new_service_account_visibility(tmp_path):
    """IAM creation can succeed before describe sees the account. Retrying
    only the read avoids a false setup failure without replaying mutations."""
    scheduler = "doug-scheduler-sa@doug-prod0.iam.gserviceaccount.com"
    lines = _run_gcp(
        tmp_path,
        "adjudicator-setup",
        extra_env={"GCLOUD_TRANSIENT_SA": scheduler},
    )

    describes = [
        line
        for line in lines
        if line.startswith(f"iam service-accounts describe {scheduler}")
    ]
    assert len(describes) == 2
```

- [ ] **Step 2: Run the new test and verify RED**

```bash
cd api
uv run pytest tests/test_deploy_gcp.py::test_adjudicator_setup_waits_for_new_service_account_visibility -q
```

Expected: FAIL because `adjudicator-setup` exits after the first invisible `describe`.

- [ ] **Step 3: Implement the bounded read-only visibility helper**

Add before `adjudicator_setup()`:

```bash
wait_for_service_account() {
  local service_account="$1" attempt=1
  while [ "$attempt" -le 10 ]; do
    if gcloud iam service-accounts describe "$service_account" \
        --project "$PROJECT" >/dev/null 2>&1; then
      return 0
    fi
    if [ "$attempt" -lt 10 ]; then
      sleep 1
    fi
    attempt=$((attempt + 1))
  done
  echo "ERROR: service account $service_account is not visible after create." >&2
  return 1
}
```

Replace both immediate M3 `describe` branches with:

```bash
wait_for_service_account "$ADJUDICATOR_SA"
```

and:

```bash
wait_for_service_account "$SCHEDULER_SA"
```

- [ ] **Step 4: Run the deployment suite and verify GREEN**

```bash
cd api
uv run pytest tests/test_deploy_gcp.py -q
bash -n deploy/gcp.sh
```

Expected: all deployment tests pass and Bash syntax is valid.

- [ ] **Step 5: Commit the propagation fix**

```bash
git add api/deploy/gcp.sh api/tests/test_deploy_gcp.py
git commit -m "fix: wait for M3 service account visibility"
```

---

### Task 3: Verify and deliver the hotfix

**Files:**
- Modify: `docs/superpowers/plans/2026-08-07-m3-deploy-hotfix.md` only if execution notes reveal a plan correction.

**Interfaces:**
- Produces: a mergeable PR against `main`; no production mutation.

- [ ] **Step 1: Run complete API verification**

```bash
cd api
uv run ruff check .
uv run pytest
uv run python scripts/read_budget_gate.py
uv run python -m doug.findings_log check
```

Expected: all checks pass; report the existing Starlette/httpx deprecation warning rather than hiding it.

- [ ] **Step 2: Verify the exact diff and base**

```bash
git diff --check
git status --short
git fetch origin main
git merge-base --is-ancestor origin/main HEAD
```

Expected: clean worktree and current `main` is an ancestor of the branch.

- [ ] **Step 3: Push and open the hotfix PR**

```bash
git push -u origin m3-deploy-hotfix
gh pr create --base main --head m3-deploy-hotfix \
  --title "Fix the M3 adjudicator deployment" \
  --body-file /tmp/doug-m3-deploy-hotfix-pr.md
```

The PR body must name the failed deployment run, state that the API was already promoted, distinguish local verification from production verification, and forbid running `schedule` until the hotfix deploy creates the Job.

- [ ] **Step 4: Wait for PR CI**

```bash
gh pr checks --watch --interval 10
```

Expected: every required check passes before handoff.

---

## Self-review

- Spec coverage: the Job argv failure, bounded read-only IAM propagation retry, loud terminal failure, exact-image invariant, no schedule, verification, and PR delivery all have explicit steps.
- Test quality: both regressions execute the real Bash script against a behavior-specific fake external CLI; neither greps the production source.
- Scope: adjudication and data semantics are untouched.
- Type consistency: `_run_gcp` keeps its `list[str]` result and gains only an optional `dict[str, str]` environment override.
