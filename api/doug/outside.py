"""Who gets a model read (ADR-0038).

A founder installation, named by the deploy, keeps today's behavior and reads
no new state. Every other installation is refused, and the refusal is posted
on the pull request as a neutral check run, never left silent.

The list is the deploy's, not the ledger's: `deploy/gcp.sh` sets it on
doug-api, a test pins it there, and the lifespan refuses to boot without it.
Nothing here names an allowance, a pool, or an admission; opening reads to
anyone else is a later, separate ruling.
"""

import os
import re
from dataclasses import dataclass
from enum import StrEnum

FOUNDER_ENV = "DOUG_FOUNDER_INSTALLATIONS"

# Every prefix a paid or traced scope carries an installation id under:
# reader.installation_scope, verify_scope, attribution_scope, carry_scope.
_TIER_PREFIXES = ("installation:", "verify:", "attribution:", "carry:")


class Reason(StrEnum):
    NOT_OPEN = "not open"


@dataclass(frozen=True)
class Founder:
    pass


@dataclass(frozen=True)
class Refused:
    reason: Reason


Decision = Founder | Refused


def _canonical(text: str) -> int | None:
    """The id `text` spells in canonical decimal, or None. "007" is not 7:
    two spellings of one id that disagree is worse than naming nobody, the
    rule reader.installation_from_scope already keeps."""
    if not text.isdigit():
        return None
    value = int(text)
    return value if str(value) == text else None


def parse_founders(raw: str) -> frozenset[int]:
    """Canonical decimal ids separated by commas or whitespace.

    Whitespace as well as commas, because gcloud's --set-env-vars splits its
    argument on commas: deploy/gcp.sh writes this list space-separated. Any
    other entry raises ValueError. A typo here would refuse the founder (R1),
    so it fails the boot (require_founders), never a job.
    """
    ids: set[int] = set()
    for entry in re.split(r"[\s,]+", raw.strip()):
        if not entry:
            continue
        value = _canonical(entry)
        if value is None:
            raise ValueError(f"{FOUNDER_ENV} entry {entry!r} is not a canonical installation id")
        ids.add(value)
    return frozenset(ids)


def founder_installations() -> frozenset[int]:
    """The deploy's founder list. Empty when unset, which refuses everyone,
    the founder included: the lifespan refuses to boot that way whenever the
    App is enabled, so a lost list fails the deploy instead of darkening the
    dogfood."""
    return parse_founders(os.environ.get(FOUNDER_ENV, ""))


def require_founders() -> frozenset[int]:
    """The boot check: the founder list, or RuntimeError when it is empty or
    malformed. A candidate revision that cannot boot is never promoted."""
    try:
        founders = founder_installations()
    except ValueError as e:
        raise RuntimeError(f"{e}; refusing to serve") from e
    if not founders:
        raise RuntimeError(
            f"{FOUNDER_ENV} is unset; refusing to serve: every installation, "
            "the founder's included, would be refused a read"
        )
    return founders


def decide(installation_id: int | None, founders: frozenset[int]) -> Decision:
    """Founder for a listed installation; every other answer is a refusal,
    an unknown or missing id included. Fails closed."""
    if installation_id is not None and installation_id in founders:
        return Founder()
    return Refused(Reason.NOT_OPEN)


def refusal_for(installation_id: int | None) -> Refused | None:
    """The refusal this installation gets under the deploy's list, or None
    for a founder. What every call site asks."""
    decision = decide(installation_id, founder_installations())
    return decision if isinstance(decision, Refused) else None


def installation_of(scope: str) -> int | None:
    """The installation a charge or span scope names, under any tier prefix,
    in the canonical form reader.installation_from_scope accepts. None for
    the un-tenanted scopes (reader.SENTINEL_SCOPE and its prefixed forms),
    which keep today's behavior."""
    for prefix in _TIER_PREFIXES:
        if scope.startswith(prefix):
            return _canonical(scope[len(prefix) :])
    return None
