from doug import keyformat


def test_generate_round_trips_through_parse():
    minted = keyformat.generate()
    assert minted.token.startswith(keyformat.PREFIX)
    parsed = keyformat.parse(minted.token)
    assert parsed is not None
    assert parsed.lookup == minted.lookup
    assert parsed.secret == minted.secret
    assert minted.last4 == minted.secret[-4:]


def test_lookup_and_secret_have_the_specified_lengths():
    minted = keyformat.generate()
    assert len(minted.lookup) == keyformat.LOOKUP_LEN == 8
    assert len(minted.secret) == keyformat.SECRET_LEN == 43


def test_parse_rejects_a_flipped_character_via_crc():
    """The CRC is a scanner-noise filter with zero security weight, but it
    must actually filter: a corrupted token dies offline, before any DB hit."""
    token = keyformat.generate().token
    # Flip one character inside the secret region (after prefix + lookup + '_').
    i = len(keyformat.PREFIX) + keyformat.LOOKUP_LEN + 1 + 5
    flipped = token[:i] + ("A" if token[i] != "A" else "B") + token[i + 1 :]
    assert keyformat.parse(flipped) is None


def test_parse_rejects_the_reserved_test_prefix():
    """doug_test_ must hard-fail rather than fall through to any other
    verifier — the same guard lema's ChainVerifier polices independently."""
    minted = keyformat.generate()
    impostor = keyformat.TEST_PREFIX + minted.token[len(keyformat.PREFIX) :]
    assert keyformat.parse(impostor) is None


def test_parse_rejects_legacy_and_junk_shapes():
    assert keyformat.parse("") is None
    assert keyformat.parse("doug_" + "x" * 43) is None          # PR #48 legacy shape
    assert keyformat.parse(keyformat.PREFIX) is None            # nothing after prefix
    assert keyformat.parse(keyformat.PREFIX + "short_x") is None
    minted = keyformat.generate()
    assert keyformat.parse(minted.token + "z") is None          # wrong tail length
    assert keyformat.parse(minted.token.replace("_", "-", 2)) is None


def test_two_generates_never_collide():
    a, b = keyformat.generate(), keyformat.generate()
    assert a.token != b.token
    assert a.lookup != b.lookup
