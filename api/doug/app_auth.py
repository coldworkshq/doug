"""GitHub App credentials — the identity every App-driven call runs under.

Two secrets, both required together: DOUG_GITHUB_APP_ID (plain env) and
GITHUB_APP_PRIVATE_KEY (the PEM, from Secret Manager). Opt-in like
reader.enabled(): a deployment without both simply has no App path, and
callers check rather than catching.

Clients are built per call, not cached. githubkit's strategies mint and
refresh their own JWT / installation token, and an installation token is
scoped to one installation for one hour — a shared client would be the
wrong tenant's credential for every request after the first.
"""

import os

from githubkit import AppAuthStrategy, AppInstallationAuthStrategy, GitHub


def app_id() -> str | None:
    """Doug's GitHub App id, or None when this deployment has none.

    Its own accessor because entitlements.py needs the id WITHOUT the private
    key: telling Doug's installations apart from every other app's in a
    caller's GET /user/installations is a fact about the app, not a
    credential, and requiring the PEM for it would tie an identity read to a
    secret it does not use. One place knows the variable's name.
    """
    return os.environ.get("DOUG_GITHUB_APP_ID")


def enabled() -> bool:
    return bool(app_id() and os.environ.get("GITHUB_APP_PRIVATE_KEY"))


def _credentials() -> tuple[str, str]:
    if not enabled():
        raise RuntimeError("DOUG_GITHUB_APP_ID and GITHUB_APP_PRIVATE_KEY must both be set")
    # Secret Manager delivers real newlines, but a PEM pasted into a shell
    # env or a .env file arrives with them escaped, and PyJWT rejects that
    # with an opaque key-format error. Base64 never contains a backslash,
    # so this is safe on a well-formed key.
    key = os.environ["GITHUB_APP_PRIVATE_KEY"].replace("\\n", "\n")
    return os.environ["DOUG_GITHUB_APP_ID"], key


def app_client() -> GitHub:
    """App-level JWT client — installation discovery and token minting only."""
    app_id, key = _credentials()
    return GitHub(AppAuthStrategy(app_id=app_id, private_key=key))


def installation_client(installation_id: int) -> GitHub:
    """A client scoped to one installation's repositories."""
    app_id, key = _credentials()
    return GitHub(
        AppInstallationAuthStrategy(
            app_id=app_id, private_key=key, installation_id=installation_id
        )
    )
