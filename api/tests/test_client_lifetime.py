"""Every GitHub client must be bound to a local for the life of its call.

githubkit's `.rest` namespace holds its client with a weakref, so
`make_client().rest.x.y()` deallocates the client the instant `.rest` is
evaluated and raises "GitHub client has already been collected" on the next
attribute — before any request, which is why no test that stubs a client
factory wholesale can reproduce it. `test_app_auth.py` pins that mechanism
against real githubkit; this file pins the codebase against writing it.

The rule was already stated in a comment (`tenancy.py`) when the adjudicator
was written with the defect anyway, and shipped, and ran red in production
for two days against a green suite. A comment cannot fail. This can.
"""

import ast
from pathlib import Path

import doug

# Every function in the codebase that returns a live githubkit client.
CLIENT_FACTORIES = frozenset(
    {
        "GitHub",
        "app_client",
        "installation_client",
        "_caller_client",
    }
)

SOURCE_ROOT = Path(doug.__file__).parent


def _unbound_client_chains() -> list[str]:
    """Attribute accesses taken directly off a client factory's return value."""
    found = []
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute) or not isinstance(node.value, ast.Call):
                continue
            func = node.value.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in CLIENT_FACTORIES:
                found.append(
                    f"{path.relative_to(SOURCE_ROOT)}:{node.value.lineno} "
                    f"— {name}(...).{node.attr}"
                )
    return found


def test_no_call_site_chains_off_a_client_factory():
    """A new call site written as `app_client().rest.x.y()` raises in
    production and nowhere else. Delete the bind at `outcome_worker`'s
    `_github_context` and this test names the line."""
    assert _unbound_client_chains() == []


def test_the_guard_detects_the_shape_it_exists_to_ban():
    """A guard that cannot see the defect is the defect. This proves the AST
    walk matches a real chain, so an empty result above means clean, not blind."""
    tree = ast.parse("app_auth.app_client().rest.apps.create_installation_access_token(1)")
    chains = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Call)
        and getattr(node.value.func, "attr", "") in CLIENT_FACTORIES
    ]
    assert len(chains) == 1
    assert chains[0].attr == "rest"
