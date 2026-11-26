"""Public bitcoin data read and checked (requirements S1.6.1, S1.6.3): every address and key that
isn't one refused with its code and words, every secret recognised, the encodings both ways, and
the curve's edge cases."""

import hashlib

import pytest

from moolakata.bitcoin import descriptor as dsc
from moolakata.bitcoin import keys as bk

ZPUB = (
    "zpub6rFR7y4Q2AijBEqTUquhVz398htDFrtymD9xYYfG1m4wAcvPhXNfE3EfH1r1ADqtfSdVCToUG868Rv"
    "UUkgDKf31mGDtKsAYz2oz2AGutZYs"
)
FIRST = "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"  # BIP 84's receive 0
P2PKH = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"
P2SH = "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"


def _with(raw_key: str, version: str | None = None, at: int | None = None, byte: int = 0) -> str:
    """An extended key with another version, or one byte of it changed."""
    raw = bytearray(bk.b58check_decode(raw_key))
    if version:
        raw[:4] = bytes.fromhex(version)
    if at is not None:
        raw[at] = byte
    return bk.b58check_encode(bytes(raw))


def _bech32(version: int, groups: list[int], const: int) -> str:
    """A bech32 string with a correct checksum over whatever it holds."""
    data = [version, *groups]
    pm = bk._polymod(bk._hrp("bc") + data + [0] * 6) ^ const
    check = [(pm >> 5 * (5 - i)) & 31 for i in range(6)]
    return "bc1" + "".join(bk.BECH32[d] for d in data + check)


def _groups(program: bytes) -> list[int]:
    return bk._convert(program, 8, 5, True)


def _off_curve() -> bytes:
    x = 1
    while True:
        y2 = (x**3 + 7) % bk.P
        if pow(y2, (bk.P - 1) // 2, bk.P) != 1:
            return b"\x02" + x.to_bytes(32, "big")
        x += 1


NOT_SEGWIT = {
    "a character bech32 has no place for": "bc1qb" + "q" * 38,
    "its checksum wrong": FIRST[:-1] + ("q" if FIRST[-1] != "q" else "p"),
    "its padding not zeros": _bech32(0, [0] * 33, 1),
    "a version past 16": _bech32(17, _groups(bytes(20)), bk.BECH32M),
    "version 0 in bech32m": _bech32(0, _groups(bytes(20)), bk.BECH32M),
    "version 1 in bech32": _bech32(1, _groups(bytes(32)), 1),
    "version 0 of 25 bytes": _bech32(0, _groups(bytes(25)), 1),
}


@pytest.mark.parametrize("what", NOT_SEGWIT)
def test_what_isnt_a_segwit_address_is_refused_as_no_address(what):
    text = NOT_SEGWIT[what]
    assert bk.segwit_decode(text) is None
    with pytest.raises(bk.Refused) as e:
        bk.address_script(text)
    assert (e.value.code, str(e.value)) == (
        "address-invalid",
        "Not a bitcoin address: check it was copied whole.",
    )


def test_a_segwit_version_not_read_is_refused_saying_so():
    with pytest.raises(bk.Refused) as e:
        bk.address_script(bk.segwit_encode(2, bytes(20)))
    assert (e.value.code, str(e.value)) == (
        "address-invalid",
        "A segwit version MoolaKata doesn't read.",
    )


KEYS = {
    "a testnet key": (_with(ZPUB, "043587cf"), "testnet",
                      "A testnet key: MoolaKata follows mainnet bitcoin only."),
    "a multisig Zpub": (_with(ZPUB, "02aa7ed3"), "key-invalid", "Not an xpub, ypub or zpub."),
    "a key not compressed": (_with(ZPUB, at=45, byte=4), "key-invalid",
                             "Not a valid extended public key."),
    "a key off the curve": (bk.b58check_encode(bk.b58check_decode(ZPUB)[:45] + _off_curve()),
                            "key-invalid", "Not a valid extended public key."),
}  # fmt: skip


@pytest.mark.parametrize("what", KEYS)
def test_an_extended_key_that_isnt_a_mainnet_public_one_is_refused(what):
    text, code, words = KEYS[what]
    with pytest.raises(bk.Refused) as e:
        bk.parse(text)
    assert (e.value.code, str(e.value)) == (code, words)


def test_an_extended_private_key_is_refused_even_past_the_secret_check():
    """parse() and the descriptor's key refuse one first; extended() refuses it too."""
    xprv = _with(ZPUB, "0488ade4")
    with pytest.raises(bk.Refused) as e:
        bk.extended(xprv)
    assert e.value.code == "private-key"
    assert xprv not in str(e.value)


def test_a_secret_in_a_wallets_text_is_refused_naming_its_kind():
    with pytest.raises(bk.Refused) as e:
        bk.parse("abandon " * 11 + "about")
    assert (e.value.code, str(e.value)) == ("secret-refused", bk.REFUSAL.format(what="seed phrase"))


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        (" ".join(["abandon"] * 5 + ["abandonn"] + ["abandon"] * 6), "seed phrase"),
        ("xprv1234", "extended private key"),
        ("5" * 51, None),  # a WIF's length and first character, but no WIF
    ],
    ids=["one word mistyped", "a short xprv", "WIF-shaped"],
)
def test_secrets_are_recognised_at_their_edges(text, kind):
    assert bk.secret_kind(text) == kind


def test_a_wallets_text_holds_descriptors_keys_and_addresses_each_once():
    x = bk.b58check_encode(bytes.fromhex("0488b21e") + bk.b58check_decode(ZPUB)[4:])
    d = dsc.parse(f"wpkh({x}/<0;1>/*)").text()
    got = bk.parse(f"{d}\n{d}\n{ZPUB}, {P2PKH} {P2PKH}")
    assert [(e.kind, e.value, e.script) for e in got] == [
        ("descriptor", d, "p2wpkh"),
        ("xpub", ZPUB, "p2wpkh"),
        ("address", P2PKH, "p2pkh"),
    ]


@pytest.mark.parametrize("address", [FIRST, P2PKH, P2SH, bk.segwit_encode(1, bytes(32))])
def test_an_addresss_script_reads_back_as_the_address(address):
    assert bk.address_of_script(bk.script_of(address)) == address


def test_a_script_no_address_has_and_an_address_no_script_has():
    assert bk.address_of_script(b"\x6a\x04abcd") is None  # an OP_RETURN
    with pytest.raises(bk.Refused) as e:
        bk.script_of("not an address")
    assert e.value.code == "address-invalid"


@pytest.mark.parametrize(
    ("message", "digest"),
    [  # the published test vectors
        (b"", "9c1185a5c5e9fc54612808977ee8f548b2258d31"),
        (b"abc", "8eb208f7e05d987a9b044a8e98c6b087f15a0bfc"),
        (b"message digest", "5d0689ef49d2fae572b881b123a85ffa21595f36"),
        (b"1234567890" * 8, "9b752e45573d4b39f4dbd3323cab82bf63326bfb"),
        (
            b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq",
            "12a053384a9c0c88e405a06c27dcf49ada62eb2b",
        ),
    ],
    ids=["empty", "abc", "message digest", "80 digits", "56 letters"],
)
def test_ripemd160_in_python_gives_the_published_digests(message, digest):
    assert bk.ripemd160(message).hex() == digest
    assert bk.ripemd160(message) == hashlib.new("ripemd160", message).digest()


def test_hash160_is_the_same_without_openssls_legacy_digests(monkeypatch):
    """A crash before: the fallback asked cryptography for a RIPEMD-160 it doesn't have."""
    want = bk.hash160(b"moolakata")

    def no_legacy(name, *args):
        raise ValueError(f"unsupported hash type {name}")

    monkeypatch.setattr(bk.hashlib, "new", no_legacy)
    assert bk.hash160(b"moolakata") == want


def test_points_add_as_the_curve_does():
    g = bk.G
    assert bk._add(None, g) == g and bk._add(g, None) == g
    assert bk._add(g, (g[0], bk.P - g[1])) is None, "a point and its negation"


def test_a_public_key_never_derives_a_hardened_or_invalid_child(monkeypatch):
    key = bk.extended(ZPUB)
    with pytest.raises(ValueError, match="hardened"):
        key.child(2**31)
    # Each has a chance of about 2^-128: the order lowered, or the tweak made the key's
    # negation, to reach them.
    monkeypatch.setattr(bk, "N", 1)
    with pytest.raises(ValueError, match="invalid child"):
        key.child(0)
    monkeypatch.undo()
    x, y = bk._point(key.key)
    monkeypatch.setattr(bk, "_mul", lambda k, pt=bk.G: (x, bk.P - y))
    with pytest.raises(ValueError, match="invalid child"):
        key.child(0)
