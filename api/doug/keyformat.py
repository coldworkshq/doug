"""The doug_live_ token format: generate, parse, offline checksum.

Pure functions over stdlib only — no storage, no config. The format follows
GitHub's token-format design (greppable literal prefix + base62 + CRC32 tail)
so secret scanners get near-zero false positives without a database hit. The
CRC carries ZERO security weight: it filters corruption and scanner noise,
nothing else. Security lives in the 256-bit secret and the peppered HMAC
stored by tenancy.py.
"""

import secrets
import zlib
from typing import NamedTuple

PREFIX = "doug_live_"
# Reserved for a future sandbox tier. parse() rejects it TODAY so a test key
# can never fall through to a different verifier that treats it as live.
TEST_PREFIX = "doug_test_"

_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
LOOKUP_LEN = 8   # plaintext key id: btree point-lookup, safe in logs and UI
SECRET_LEN = 43  # 43 base62 chars ≈ 256 bits of entropy
CRC_LEN = 6      # CRC32 max fits in 6 base62 chars (62^6 > 2^32)


class Minted(NamedTuple):
    token: str
    lookup: str
    secret: str
    last4: str


class Parsed(NamedTuple):
    lookup: str
    secret: str


def _b62(n: int, width: int) -> str:
    out = []
    while n:
        n, r = divmod(n, 62)
        out.append(_ALPHABET[r])
    return ("".join(reversed(out)) or "0").rjust(width, "0")


def _crc(lookup: str, secret: str) -> str:
    return _b62(zlib.crc32((lookup + secret).encode()), CRC_LEN)


def _rand(width: int) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(width))


def generate() -> Minted:
    lookup = _rand(LOOKUP_LEN)
    secret = _rand(SECRET_LEN)
    token = f"{PREFIX}{lookup}_{secret}{_crc(lookup, secret)}"
    return Minted(token=token, lookup=lookup, secret=secret, last4=secret[-4:])


def parse(token: str) -> Parsed | None:
    """A structurally valid doug_live_ token's parts, or None.

    Rejection order matters only for TEST_PREFIX: it must be recognized and
    refused explicitly, never treated as 'not ours'.
    """
    if token.startswith(TEST_PREFIX):
        return None
    if not token.startswith(PREFIX):
        return None
    rest = token[len(PREFIX):]
    lookup, sep, tail = rest.partition("_")
    if sep != "_" or len(lookup) != LOOKUP_LEN or len(tail) != SECRET_LEN + CRC_LEN:
        return None
    secret, crc = tail[:SECRET_LEN], tail[SECRET_LEN:]
    if any(c not in _ALPHABET for c in lookup + secret + crc):
        return None
    if crc != _crc(lookup, secret):
        return None
    return Parsed(lookup=lookup, secret=secret)
