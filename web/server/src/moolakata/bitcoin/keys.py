"""Public bitcoin data (requirements S1.6.1, S1.6.3): addresses checked, extended public keys
(xpub, ypub, zpub) read and their addresses derived (BIP32 public derivation, the receive chain
0/i and change chain 1/i), and anything that looks like a private key or seed phrase refused.
Mainnet only. Nothing here ever holds or logs a secret: a refusal names the kind, not the value."""

import hashlib
import hmac
import re
from dataclasses import dataclass
from pathlib import Path

# secp256k1
P = 2**256 - 2**32 - 977
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
G = (
    0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
    0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8,
)

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
BECH32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"

# Extended public keys by version: the script their addresses use (BIP44, BIP49, BIP84).
PUBLIC = {
    bytes.fromhex("0488b21e"): "p2pkh",  # xpub
    bytes.fromhex("049d7cb2"): "p2sh-p2wpkh",  # ypub
    bytes.fromhex("04b24746"): "p2wpkh",  # zpub
}
PRIVATE = {
    bytes.fromhex(v)
    for v in ("0488ade4", "049d7878", "04b2430c", "04358394", "044a4e28", "045f18bc")
}  # xprv, yprv, zprv, tprv, uprv, vprv
TESTNET = {bytes.fromhex(v) for v in ("043587cf", "044a5262", "045f1cf6")}  # tpub, upub, vpub


class Refused(ValueError):
    """Text that is not public bitcoin data. `code` says what it looked like."""

    # Every code it is made with: a wallet's keys are refused by it, so the OpenAPI document
    # lists them (S13.8.3).
    CODES = (
        "address-invalid",
        "descriptor-checksum",
        "descriptor-ending",
        "descriptor-invalid",
        "descriptor-unsupported",
        "key-invalid",
        "private-key",
        "secret-refused",
        "testnet",
    )

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ---- encodings


def _sha256d(b: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(b).digest()).digest()


def _ripemd160(b: bytes) -> bytes:
    try:
        return hashlib.new("ripemd160", b).digest()
    except ValueError:  # an OpenSSL without its legacy digests
        from cryptography.hazmat.primitives import hashes

        h = hashes.Hash(hashes.RIPEMD160())
        h.update(b)
        return h.finalize()


def hash160(b: bytes) -> bytes:
    return _ripemd160(hashlib.sha256(b).digest())


def b58check_decode(s: str) -> bytes | None:
    n = 0
    for ch in s:
        i = B58.find(ch)
        if i < 0:
            return None
        n = n * 58 + i
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    raw = b"\0" * (len(s) - len(s.lstrip("1"))) + raw
    if len(raw) < 5 or _sha256d(raw[:-4])[:4] != raw[-4:]:
        return None
    return raw[:-4]


def b58check_encode(b: bytes) -> str:
    raw = b + _sha256d(b)[:4]
    n = int.from_bytes(raw, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    return "1" * (len(raw) - len(raw.lstrip(b"\0"))) + out


def _polymod(values) -> int:
    gen = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    chk = 1
    for v in values:
        top = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i in range(5):
            chk ^= gen[i] if (top >> i) & 1 else 0
    return chk


def _hrp(hrp: str) -> list[int]:
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


BECH32M = 0x2BC830A3


def _convert(data, frm: int, to: int, pad: bool) -> list[int] | None:
    acc = bits = 0
    out = []
    maxv = (1 << to) - 1
    for v in data:
        if v < 0 or v >> frm:
            return None
        acc = acc << frm | v
        bits += frm
        while bits >= to:
            bits -= to
            out.append(acc >> bits & maxv)
    if pad and bits:
        out.append(acc << (to - bits) & maxv)
    elif not pad and (bits >= frm or acc << (to - bits) & maxv):
        return None
    return out


def segwit_encode(version: int, program: bytes, hrp: str = "bc") -> str:
    data = [version, *_convert(program, 8, 5, True)]
    const = 1 if version == 0 else BECH32M
    pm = _polymod(_hrp(hrp) + data + [0] * 6) ^ const
    check = [(pm >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(BECH32[d] for d in data + check)


def segwit_decode(addr: str, hrp: str = "bc") -> tuple[int, bytes] | None:
    if addr.lower() != addr and addr.upper() != addr:
        return None
    addr = addr.lower()
    pos = addr.rfind("1")
    if addr[:pos] != hrp or pos + 7 > len(addr) or len(addr) > 90:
        return None
    try:
        data = [BECH32.index(c) for c in addr[pos + 1 :]]
    except ValueError:
        return None
    const = _polymod(_hrp(hrp) + data)
    if const not in (1, BECH32M):
        return None
    version = data[0]
    prog = _convert(data[1:-6], 5, 8, False)
    if prog is None or version > 16 or not 2 <= len(prog) <= 40:
        return None
    if (version == 0) != (const == 1):
        return None
    if version == 0 and len(prog) not in (20, 32):
        return None
    return version, bytes(prog)


# ---- secp256k1 public derivation


def _add(a, b):
    if a is None:
        return b
    if b is None:
        return a
    if a[0] == b[0] and (a[1] + b[1]) % P == 0:
        return None
    if a == b:
        m = 3 * a[0] * a[0] * pow(2 * a[1], -1, P) % P
    else:
        m = (b[1] - a[1]) * pow(b[0] - a[0], -1, P) % P
    x = (m * m - a[0] - b[0]) % P
    return x, (m * (a[0] - x) - a[1]) % P


def _mul(k: int, pt=G):
    out = None
    while k:
        if k & 1:
            out = _add(out, pt)
        pt = _add(pt, pt)
        k >>= 1
    return out


def _point(sec: bytes):
    if len(sec) != 33 or sec[0] not in (2, 3):
        raise ValueError("not a compressed public key")
    x = int.from_bytes(sec[1:], "big")
    y = pow((x * x * x + 7) % P, (P + 1) // 4, P)
    if (y * y - x * x * x - 7) % P:
        raise ValueError("not on the curve")
    if y & 1 != sec[0] & 1:
        y = P - y
    return x, y


def _sec(pt) -> bytes:
    return bytes([2 + (pt[1] & 1)]) + pt[0].to_bytes(32, "big")


@dataclass(frozen=True)
class ExtendedKey:
    script: str  # p2pkh, p2sh-p2wpkh or p2wpkh
    depth: int
    chain: bytes
    key: bytes  # compressed public key

    def child(self, i: int) -> ExtendedKey:
        if i >= 2**31:
            raise ValueError("a public key can't derive hardened children")
        h = hmac.new(self.chain, self.key + i.to_bytes(4, "big"), hashlib.sha512).digest()
        t = int.from_bytes(h[:32], "big")
        if t >= N:
            raise ValueError("invalid child")
        pt = _add(_mul(t), _point(self.key))
        if pt is None:
            raise ValueError("invalid child")
        return ExtendedKey(self.script, self.depth + 1, h[32:], _sec(pt))

    def address(self, chain: int, index: int) -> str:
        return address_of(self.child(chain).child(index).key, self.script)


def address_of(pub: bytes, script: str) -> str:
    h = hash160(pub)
    if script == "p2pkh":
        return b58check_encode(b"\x00" + h)
    if script == "p2sh-p2wpkh":
        return b58check_encode(b"\x05" + hash160(b"\x00\x14" + h))
    return segwit_encode(0, h)


def extended(s: str) -> ExtendedKey:
    """An xpub, ypub or zpub, read; Refused for a private or testnet key, or a bad one."""
    raw = b58check_decode(s)
    if raw is None or len(raw) != 78:
        raise Refused("key-invalid", "Not a valid extended public key: check it was copied whole.")
    version = raw[:4]
    if version in PRIVATE:
        raise Refused(
            "private-key",
            "That is an extended private key. MoolaKata never accepts one: export the "
            "extended public key (xpub, ypub or zpub) instead. Nothing was saved.",
        )
    if version in TESTNET:
        raise Refused("testnet", "A testnet key: MoolaKata follows mainnet bitcoin only.")
    if version not in PUBLIC:
        raise Refused("key-invalid", "Not an xpub, ypub or zpub.")
    key = raw[45:]
    try:
        _point(key)
    except ValueError:
        raise Refused("key-invalid", "Not a valid extended public key.") from None
    return ExtendedKey(PUBLIC[version], raw[4], raw[13:45], key)


def address_script(s: str) -> str:
    """A mainnet address's script; Refused when it isn't one."""
    seg = segwit_decode(s)
    if seg is not None:
        version, prog = seg
        if version == 0:
            return "p2wpkh" if len(prog) == 20 else "p2wsh"
        if version == 1 and len(prog) == 32:
            return "p2tr"
        raise Refused("address-invalid", "A segwit version MoolaKata doesn't read.")
    raw = b58check_decode(s)
    if raw is not None and len(raw) == 21 and raw[0] in (0, 5):
        return "p2pkh" if raw[0] == 0 else "p2sh"
    if s[:1] in "mn2" or s.lower().startswith(("tb1", "bcrt1")):
        raise Refused("testnet", "A testnet address: MoolaKata follows mainnet bitcoin only.")
    raise Refused("address-invalid", "Not a bitcoin address: check it was copied whole.")


# ---- secrets refused


_WORDS: set[str] | None = None


def _bip39() -> set[str]:
    global _WORDS
    if _WORDS is None:
        f = Path(__file__).parent.parent / "keys" / "bip39-english.txt"
        _WORDS = set(f.read_text().split())
    return _WORDS


REFUSAL = (
    "That looks like a {what}. MoolaKata never accepts one, and nothing was saved: enter an "
    "extended public key (xpub, ypub or zpub), a public descriptor or addresses instead."
)


_NUMBER = re.compile(r"\d+[.):]?")
_WORD = re.compile(r"(?:\d+[.):]?)?([a-z]+)[.]?")


def _seed_phrase(text: str) -> bool:
    """Twelve BIP-39 words in a row, one of them perhaps mistyped, however they are separated
    or numbered: by spaces, lines or commas, as `1. abandon` or `1) abandon` (S1.6.3)."""
    run = misses = 0
    for tok in re.split(r"[\s,;]+", text.lower()):
        if not tok or _NUMBER.fullmatch(tok):
            continue
        m = _WORD.fullmatch(tok)
        if m and m.group(1) in _bip39():
            run += 1
        elif run and not misses:
            run, misses = run + 1, 1
        else:
            run = misses = 0
        if run >= 12:
            return True
    return False


def secret_kind(text: str) -> str | None:
    """What secret the text looks like, if it looks like one: a seed phrase, a private key in
    WIF or hex, or an extended private key, alone or inside a descriptor."""
    if _seed_phrase(text):
        return "seed phrase"
    if re.search(r"[xyztuv]prv[1-9A-HJ-NP-Za-km-z]{100,}", text):
        return "extended private key"
    for tok in re.split(r"[^0-9A-Za-z]+", text):
        if len(tok) == 64 and all(c in "0123456789abcdefABCDEF" for c in tok):
            return "private key (64 hex digits)"
        if tok[:4] in ("xprv", "yprv", "zprv", "tprv", "uprv", "vprv"):
            return "extended private key"
        if len(tok) in (51, 52) and tok[0] in "5KLc9":
            raw = b58check_decode(tok)
            if raw is not None and raw[0] in (0x80, 0xEF):
                return "private key (WIF)"
    return None


@dataclass
class Entry:
    kind: str  # xpub, descriptor or address
    value: str
    script: str


def parse(text: str) -> list[Entry]:
    """What a wallet's form holds: extended public keys and addresses, one a line or separated
    by spaces or commas. Refused, naming the first problem, for a secret or a bad entry."""
    what = secret_kind(text)
    if what:
        raise Refused("secret-refused", REFUSAL.format(what=what))
    out: list[Entry] = []
    seen = set()
    from . import descriptor

    # A descriptor holds commas and is one a line (S1.6.1.4); the rest are tokens.
    rest = []
    for line in text.splitlines():
        if descriptor.looks_like(line):
            d = descriptor.parse(line)
            value = d.text()
            if value not in seen:
                seen.add(value)
                out.append(Entry("descriptor", value, d.script))
        else:
            rest.append(line)
    for tok in " ".join(rest).replace(",", " ").split():
        if tok in seen:
            continue
        seen.add(tok)
        if tok[1:4] == "pub" and len(tok) > 100:
            out.append(Entry("xpub", tok, extended(tok).script))
        else:
            out.append(Entry("address", tok, address_script(tok)))
    return out


def script_of(address: str) -> bytes:
    """An address's scriptPubKey: what an Electrum server indexes it by."""
    seg = segwit_decode(address)
    if seg is not None:
        version, prog = seg
        return bytes([0x50 + version if version else 0, len(prog)]) + prog
    raw = b58check_decode(address)
    if raw is None or len(raw) != 21:
        raise Refused("address-invalid", "Not a bitcoin address.")
    if raw[0] == 0:
        return b"\x76\xa9\x14" + raw[1:] + b"\x88\xac"
    return b"\xa9\x14" + raw[1:] + b"\x87"


def address_of_script(script: bytes) -> str | None:
    if len(script) == 25 and script[:3] == b"\x76\xa9\x14" and script[23:] == b"\x88\xac":
        return b58check_encode(b"\x00" + script[3:23])
    if len(script) == 23 and script[:2] == b"\xa9\x14" and script[22:] == b"\x87":
        return b58check_encode(b"\x05" + script[2:22])
    if (
        len(script) >= 4
        and (script[0] == 0 or 0x51 <= script[0] <= 0x60)
        and script[1] == len(script) - 2
    ):
        return segwit_encode(script[0] - 0x50 if script[0] else 0, script[2:])
    return None
