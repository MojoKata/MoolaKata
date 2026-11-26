"""Output descriptors (requirements S1.6.1.4): the BIP 380 checksum, single-key and multisig
descriptors, BIP 86 taproot, and the refusals."""

import hashlib

import pytest

from moolakata.bitcoin import descriptor as dsc
from moolakata.bitcoin import keys as bk

# BIP 86's and BIP 84's test vectors, from "abandon … about".
TR_XPUB = (
    "xpub6BgBgsespWvERF3LHQu6CnqdvfEvtMcQjYrcRzx53QJjSxarj2afYWcLteoGVky7D3UKDP9QyrLprQ3VCECoY49y"
    "fdDEHGCtMMj92pReUsQ"
)
ZPUB = (
    "zpub6rFR7y4Q2AijBEqTUquhVz398htDFrtymD9xYYfG1m4wAcvPhXNfE3EfH1r1ADqtfSdVCToUG868RvUUkgDKf31m"
    "GDtKsAYz2oz2AGutZYs"
)


def as_xpub(z: str) -> str:
    raw = bk.b58check_decode(z)
    return bk.b58check_encode(bytes.fromhex("0488b21e") + raw[4:])


def test_the_checksum_is_bip_380s():
    assert dsc.checksum("raw(deadbeef)") == "89f8spxm"


def test_taproot_derives_bip_86s_addresses():
    d = dsc.parse(f"tr([73c5da0a/86'/0'/0']{TR_XPUB}/<0;1>/*)")
    assert (d.kind, d.chains, d.script) == ("tr", (0, 1), "p2tr")
    assert d.address(0, 0) == "bc1p5cyxnuxmeuwuvkwfem96lqzszd02n6xdcjrs20cac6yqjjwudpxqkedrcr"


def test_single_key_descriptors_match_their_extended_keys():
    x = as_xpub(ZPUB)
    d = dsc.parse(f"wpkh([73c5da0a/84'/0'/0']{x}/0/*)")
    assert d.chains == (0,)
    assert d.address(0, 0) == "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"
    assert d.address(0, 0) == bk.extended(ZPUB).address(0, 0)
    assert dsc.parse(dsc.parse(f"pkh({x}/1/*)").text()).chains == (1,)
    sh = dsc.parse(f"sh(wpkh({x}/<0;1>/*))")
    assert sh.address(1, 3).startswith("3")


def test_a_multisig_is_derived_from_all_its_keys():
    x = as_xpub(ZPUB)
    d = dsc.parse(f"wsh(sortedmulti(2,[aaaaaaaa/48'/0'/0'/2']{x}/<0;1>/*,{TR_XPUB}/<0;1>/*))")
    assert (d.kind, d.threshold, len(d.keys)) == ("wsh-sortedmulti", 2, 2)
    pubs = sorted(k.key.child(0).child(5).key for k in d.keys)
    script = b"\x52" + b"".join(b"\x21" + p for p in pubs) + b"\x52\xae"
    assert d.address(0, 5) == bk.segwit_encode(0, hashlib.sha256(script).digest())
    unsorted = dsc.parse(d.body().replace("sortedmulti", "multi"))
    assert unsorted.kind == "wsh-multi"
    # Its text, with a checksum, reads back the same.
    assert dsc.parse(d.text()).address(1, 0) == d.address(1, 0)


def test_what_is_refused():
    x = as_xpub(ZPUB)
    body = f"wpkh({x}/0/*)"
    with pytest.raises(bk.Refused) as e:
        dsc.parse(body + "#aaaaaaaa")
    assert e.value.code == "descriptor-checksum"
    for text, code in (
        (f"wpkh({x}/0/1)", "descriptor-ending"),
        (f"sh(wsh(sortedmulti(1,{x}/0/*)))", "descriptor-unsupported"),
        ("wpkh(L1aW4aubDFB7yfras2S1mN3bqg9nwySY8nkoLmJebSLD5BWv3ENZ/0/*)", "private-key"),
        (
            "wpkh(xprv9s21ZrQH143K3QTDL4LXw2F7HEK3wJUD2nW2nRk4stbPy6cq3jPPqjiChkVvvNKmPGJxWUtg6LnF5kejMRNNU3TGtRBeJgk33yuGBxrMPHi/0/*)",
            "private-key",
        ),
    ):
        with pytest.raises(bk.Refused) as e:
            dsc.parse(text)
        assert e.value.code == code, text


def as_version(z: str, version: str) -> str:
    return bk.b58check_encode(bytes.fromhex(version) + bk.b58check_decode(z)[4:])


def _refusals():
    x = as_xpub(ZPUB)
    tpub = as_version(ZPUB, "043587cf")
    multi = "A multisig descriptor MoolaKata can't read."
    return (
        ("wpkh(é)#aaaaaaaa", "descriptor-invalid", "A character a descriptor can't hold."),
        (f"wpkh({x}/0/*", "descriptor-invalid", "Not a descriptor MoolaKata reads."),
        ("wpkh(0OIl/0/*)", "descriptor-invalid", "A descriptor key MoolaKata can't read."),
        (f"wpkh({tpub}/0/*)", "testnet", "A testnet key: MoolaKata follows mainnet bitcoin only."),
        (f"wpkh({ZPUB}/0/*)", "descriptor-invalid", "Each descriptor key is an xpub."),
        (f"tr({x}/0/*,{{pk({x}/1/*)}})", "descriptor-unsupported",
         "A taproot descriptor with scripts isn't read yet: its key path only."),
        (f"wsh(pk({x}/0/*))", "descriptor-unsupported",
         "Of wsh() descriptors, only sortedmulti and multi are read."),
        (f"wsh(multi(3,{x}/0/*,{TR_XPUB}/0/*))", "descriptor-invalid", multi),
        (f"wsh(multi(1,{x}/0/*,{TR_XPUB}/1/*))", "descriptor-invalid", multi),
        (f"wsh(multi(0,{x}/0/*))", "descriptor-invalid", multi),
        (f"combo({x}/0/*)", "descriptor-unsupported", "combo() descriptors aren't read."),
    )  # fmt: skip


@pytest.mark.parametrize(("text", "code", "words"), _refusals())
def test_each_refusal_says_what_is_wrong(text, code, words):
    with pytest.raises(bk.Refused) as e:
        dsc.parse(text)
    assert (e.value.code, str(e.value)) == (code, words)


def test_a_nested_segwit_descriptor_writes_out_as_read():
    x = as_xpub(ZPUB)
    d = dsc.parse(f"sh(wpkh([73c5da0a/49'/0'/0']{x}/0/*))")
    assert d.body() == f"sh(wpkh([73c5da0a/49'/0'/0']{x}/0/*))"
    assert dsc.parse(d.text()) == d


def test_an_unsorted_multisig_keeps_its_keys_order():
    x = as_xpub(ZPUB)
    for first, second in ((TR_XPUB, x), (x, TR_XPUB)):
        d = dsc.parse(f"wsh(multi(1,{first}/0/*,{second}/0/*))")
        pubs = [k.key.child(0).child(0).key for k in d.keys]
        script = b"\x51" + b"".join(b"\x21" + p for p in pubs) + b"\x52\xae"
        assert d.address(0, 0) == bk.segwit_encode(0, hashlib.sha256(script).digest())


def test_a_key_whose_tweak_is_out_of_range_makes_no_taproot_address(monkeypatch):
    """BIP 341: a tweak at or past the curve's order makes no key (a chance of about 2^-128,
    so the order is lowered to reach it)."""
    d = dsc.parse(f"tr({TR_XPUB}/0/*)")
    monkeypatch.setattr(bk, "N", 1)
    with pytest.raises(bk.Refused) as e:
        dsc.taproot(d.keys[0].key.key)
    assert e.value.code == "descriptor-invalid"
