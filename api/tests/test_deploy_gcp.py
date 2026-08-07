"""Pins that the deploy script still names the identities it claims to use.

A comment saying doug-web has its own SA is not a capability — the next
web() deploy either passes --service-account or silently runs as the
default compute SA (roles/editor on doug-prod0). Same shape as the intent
allowlist pin in test_deviations.py.
"""

import hashlib
import os
import subprocess
from pathlib import Path

GCP_PATH = Path(__file__).resolve().parents[1] / "deploy" / "gcp.sh"
GCP = GCP_PATH.read_text()


def _active_lines() -> list[str]:
    return [ln for ln in GCP.splitlines() if not ln.lstrip().startswith("#")]


def _function_body(name: str) -> str:
    """Active (non-comment) lines of `name() { … }` up to the next top-level fn."""
    lines = _active_lines()
    body: list[str] = []
    in_fn = False
    for ln in lines:
        if ln.startswith(f"{name}()"):
            in_fn = True
            continue
        if in_fn:
            # Top-level sibling function: `foo() {` at column 0.
            if ln.endswith("() {") and not ln.startswith((" ", "\t")):
                break
            body.append(ln)
    return "\n".join(body)


def test_web_deploy_runs_as_doug_web_sa():
    """The browser-facing service must not inherit the default compute SA."""
    body = _function_body("web")
    assert "--service-account" in body
    assert "doug-web-sa@$PROJECT.iam.gserviceaccount.com" in body
    assert "compute@developer.gserviceaccount.com" not in body


def test_setup_creates_doug_web_sa_and_binds_the_api_token():
    """web needs doug-api-token only — no Cloud SQL client, no App key."""
    setup = _function_body("setup")
    assert "service-accounts create doug-web-sa" in setup
    assert "doug-web-sa@$PROJECT.iam.gserviceaccount.com" in setup
    # After the web-sa create, the only secret binding is doug-api-token.
    after_web = setup.split("service-accounts create doug-web-sa", 1)[1].split(
        "service-accounts create doug-console-sa", 1
    )[0]
    assert "doug-api-token" in after_web
    assert "doug-database-url" not in after_web
    assert "doug-github-app-key" not in after_web
    assert "doug-anthropic-key" not in after_web
    assert "roles/cloudsql.client" not in after_web


def test_api_deploy_still_runs_as_doug_api_sa():
    """Don't accidentally move the API off its dedicated SA while touching web."""
    body = _function_body("deploy")
    assert "doug-api-sa@$PROJECT.iam.gserviceaccount.com" in body


def test_console_is_never_deployed_unauthenticated():
    """The console spans every installation. Deploying it open publishes
    both tenants' PR titles, job errors and coverage gaps. A comment is not
    a control — this is the control."""
    body = _function_body("console")
    assert "--no-allow-unauthenticated" in body
    assert "--allow-unauthenticated" not in body.replace("--no-allow-unauthenticated", "")
    # --no-allow-unauthenticated only blocks the default deploy-time policy.
    # A later `services add-iam-policy-binding ... --member=allUsers` — in
    # console() or in setup() — would leave both assertions above passing
    # while the service is world-readable, so this checks the whole script,
    # not just console()'s body.
    assert "allUsers" not in GCP
    assert "allAuthenticatedUsers" not in GCP


def test_console_runs_as_its_own_service_account():
    body = _function_body("console")
    assert "--service-account" in body
    assert "doug-console-sa@$PROJECT.iam.gserviceaccount.com" in body
    assert "compute@developer.gserviceaccount.com" not in body


def test_setup_creates_doug_console_sa_and_binds_only_the_api_token():
    """The console talks to doug-api over HTTP. It needs no Cloud SQL
    client, no App key, no Anthropic key."""
    setup = _function_body("setup")
    assert "service-accounts create doug-console-sa" in setup
    after = setup.split("service-accounts create doug-console-sa", 1)[1].split(
        "service-accounts create doug-adjudicator-sa", 1
    )[0]
    assert "doug-api-token" in after
    assert "doug-database-url" not in after
    assert "doug-github-app-key" not in after
    assert "doug-anthropic-key" not in after
    assert "roles/cloudsql.client" not in after


def test_web_deploy_is_still_the_only_public_service():
    """Guard against the console being folded back into web()."""
    assert "--allow-unauthenticated" in _function_body("web")
    assert "--source ../console" not in _function_body("web")


def _fake_gcloud(tmp_path: Path) -> tuple[Path, Path]:
    """A deterministic gcloud boundary: record argv, return an API image,
    and report that the Scheduler resource does not exist yet."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "gcloud.log"
    gcloud = fake_bin / "gcloud"
    gcloud.write_text(
        """#!/bin/sh
printf '%s\\n' "$*" >> "$GCLOUD_LOG"
if [ "$1 $2 $3 $4" = "run services describe doug-api" ]; then
  printf '%s\\n' 'us-docker.pkg.dev/doug-prod0/cloud-run-source-deploy/doug-api@sha256:abc123'
  exit 0
fi
if [ "$1 $2 $3" = "scheduler jobs describe" ]; then
  exit 1
fi
exit 0
"""
    )
    gcloud.chmod(0o755)
    return fake_bin, log


def _run_gcp(tmp_path: Path, command: str) -> list[str]:
    fake_bin, log = _fake_gcloud(tmp_path)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "GCLOUD_LOG": str(log),
        "PROJECT": "doug-prod0",
        "REGION": "us-central1",
    }
    result = subprocess.run(
        ["bash", str(GCP_PATH), command],
        cwd=GCP_PATH.parent.parent,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return log.read_text().splitlines()


def test_adjudicator_deploys_the_live_api_image_with_the_bounded_job_contract(tmp_path):
    """Building a second source image could fork the live detector; platform
    retries would spend several of the ten attempts on one calendar day."""
    lines = _run_gcp(tmp_path, "adjudicator")
    [deploy] = [line for line in lines if line.startswith("run jobs deploy doug-adjudicator")]
    assert (
        "--image us-docker.pkg.dev/doug-prod0/cloud-run-source-deploy/"
        "doug-api@sha256:abc123" in deploy
    )
    assert "--memory 2Gi" in deploy
    assert "--cpu 1" in deploy
    assert "--tasks 1" in deploy
    assert "--max-retries 0" in deploy
    assert "--task-timeout 3600s" in deploy
    assert "--command python" in deploy
    assert "--args -m,doug.outcome_worker" in deploy
    assert "--service-account doug-adjudicator-sa@doug-prod0.iam.gserviceaccount.com" in deploy
    assert "DATABASE_URL=doug-database-url:latest" in deploy
    assert "GITHUB_APP_PRIVATE_KEY=doug-github-app-key:latest" in deploy

    prereg = GCP_PATH.parents[2] / "docs/design/outcome-loop/publication-preregistration.md"
    expected_hash = hashlib.sha256(prereg.read_bytes()).hexdigest()
    assert f"DOUG_PREREG_HASH={expected_hash}" in deploy


def test_schedule_creates_one_daily_utc_trigger_with_a_scheduler_identity(tmp_path):
    """The runtime account reads code and secrets; granting it invocation
    authority too would collapse two unrelated identities."""
    lines = _run_gcp(tmp_path, "schedule")
    [binding] = [line for line in lines if line.startswith("run jobs add-iam-policy-binding")]
    assert "--member=serviceAccount:doug-scheduler-sa@doug-prod0.iam.gserviceaccount.com" in binding
    assert "--role=roles/run.invoker" in binding
    assert "doug-adjudicator-sa" not in binding

    [create] = [line for line in lines if line.startswith("scheduler jobs create http")]
    assert "--schedule 0 3 * * *" in create
    assert "--time-zone Etc/UTC" in create
    assert "--http-method POST" in create
    assert (
        "--oauth-service-account-email "
        "doug-scheduler-sa@doug-prod0.iam.gserviceaccount.com" in create
    )
    assert "/locations/us-central1/jobs/doug-adjudicator:run" in create


def test_api_deploy_also_refreshes_the_adjudicator_from_its_promoted_image():
    """A later detector change must not deploy to the API while the outcome
    worker keeps running an older image."""
    assert "adjudicator" in _function_body("deploy")


def test_setup_owns_scheduler_and_adjudicator_identities():
    setup = _function_body("setup")
    assert "adjudicator_setup" in setup
    adjudicator = _function_body("adjudicator_setup")
    assert "cloudscheduler.googleapis.com" in adjudicator
    assert "service-accounts create doug-adjudicator-sa" in adjudicator
    assert "service-accounts create doug-scheduler-sa" in adjudicator
    assert "doug-database-url" in adjudicator
    assert "doug-github-app-key" in adjudicator
    assert "doug-anthropic-key" not in adjudicator


def test_adjudicator_setup_is_narrow_and_never_rotates_the_database(tmp_path):
    """The broad setup command resets the production SQL password. M3 needs
    IAM and APIs only, so its operator command must be structurally unable to
    touch a SQL user or publish a new database-secret version."""
    lines = _run_gcp(tmp_path, "adjudicator-setup")
    emitted = "\n".join(lines)

    assert "services enable" in emitted
    assert "cloudscheduler.googleapis.com" in emitted
    assert "iam service-accounts create doug-adjudicator-sa" in emitted
    assert "iam service-accounts create doug-scheduler-sa" in emitted
    assert "roles/cloudsql.client" in emitted
    assert "doug-database-url" in emitted
    assert "doug-github-app-key" in emitted
    assert "sql users" not in emitted
    assert "sql databases" not in emitted
    assert "secrets versions add doug-database-url" not in emitted
