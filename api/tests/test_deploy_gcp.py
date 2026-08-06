"""Pins that the deploy script still names the identities it claims to use.

A comment saying doug-web has its own SA is not a capability — the next
web() deploy either passes --service-account or silently runs as the
default compute SA (roles/editor on doug-prod0). Same shape as the intent
allowlist pin in test_deviations.py.
"""

from pathlib import Path

GCP = (Path(__file__).resolve().parents[1] / "deploy" / "gcp.sh").read_text()


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
        if in_fn and ln.endswith("() {") and not ln[0].isspace():
            break
        if in_fn and ln == "}" and body and not body[-1].startswith(" "):
            # closing brace of the function at column 0 — rare; keep scanning
            pass
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
    after_web = setup.split("service-accounts create doug-web-sa", 1)[1]
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
    after = setup.split("service-accounts create doug-console-sa", 1)[1]
    assert "doug-api-token" in after
    assert "doug-database-url" not in after
    assert "doug-github-app-key" not in after
    assert "doug-anthropic-key" not in after
    assert "roles/cloudsql.client" not in after


def test_web_deploy_is_still_the_only_public_service():
    """Guard against the console being folded back into web()."""
    assert "--allow-unauthenticated" in _function_body("web")
    assert "--source ../console" not in _function_body("web")
