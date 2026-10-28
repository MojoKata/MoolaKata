"""Encrypted files in a linked copy (requirements S11.9.6): receipts and inbox changes, sealed to
the copy's public key so they can be written while the copy is locked, in one streaming format.

Header: `MKR1`, the one-time X25519 public key (32 bytes), a random salt (32), a nonce prefix (7)
and the chunk size (4, big-endian). Key: HKDF-SHA256 over the X25519 exchange between the
one-time key and the copy's key, with the salt, under a label naming the kind of file. Chunks:
each chunk of up to 64 KiB is sealed with AES-256-GCM, its nonce the prefix, a 4-byte counter and
a last-chunk flag, and its associated data naming the link, the file and the chunk's number. A
chunk reordered, dropped or cut off, or a file renamed onto another, fails to open. This is the
AES-GCM-HKDF streaming construction, built on `cryptography`."""

import os
import secrets
import struct
from collections.abc import Iterable, Iterator
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

MAGIC = b"MKR1"
CHUNK = 64 * 1024
TAG = 16
HEADER = len(MAGIC) + 32 + 32 + 7 + 4
RECEIPT = b"moolakata link receipt"
CHANGE = b"moolakata link change"


def sealed_size(plain: int) -> int:
    """How long a sealed file of `plain` bytes is: the header, and a tag for each chunk, the
    last of which is never full (an empty one follows a whole last chunk)."""
    return HEADER + (plain // CHUNK + 1) * TAG + plain


def max_receipt() -> int:
    """The longest a receipt crosses a link as (link-protocol.md §1.4): the largest receipt
    Settings allows, sealed. A `deliver` body and a `file` answer are bounded by it."""
    from ..settings import RECEIPT_MAX_MB

    return sealed_size(RECEIPT_MAX_MB * 1024 * 1024)


class SealError(Exception):
    """A sealed file that doesn't open: tampered with, cut off, or not this copy's."""


def _key(shared: bytes, salt: bytes, label: bytes) -> AESGCM:
    k = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=label).derive(shared)
    return AESGCM(k)


def _nonce(prefix: bytes, n: int, last: bool) -> bytes:
    return prefix + struct.pack(">I", n) + (b"\x01" if last else b"\x00")


def _aad(link_id: str, name: str, n: int) -> bytes:
    return f"{link_id}\n{name}\n{n}".encode()


def _chunks(data: Iterable[bytes]) -> Iterator[bytes]:
    """The input as 64 KiB pieces, whatever sizes it arrives in."""
    buf = b""
    for piece in data:
        buf += piece
        while len(buf) >= CHUNK:
            yield buf[:CHUNK]
            buf = buf[CHUNK:]
    yield buf


def seal(
    public: bytes, label: bytes, link_id: str, name: str, data: Iterable[bytes]
) -> Iterator[bytes]:
    """The sealed file, piece by piece: the header, then each chunk."""
    eph = X25519PrivateKey.generate()
    salt, prefix = secrets.token_bytes(32), secrets.token_bytes(7)
    aead = _key(eph.exchange(X25519PublicKey.from_public_bytes(public)), salt, label)
    yield (
        MAGIC
        + eph.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        + salt
        + prefix
        + struct.pack(">I", CHUNK)
    )
    it = _chunks(data)
    n, cur = 0, next(it)
    for nxt in it:
        yield aead.encrypt(_nonce(prefix, n, False), cur, _aad(link_id, name, n))
        n, cur = n + 1, nxt
    yield aead.encrypt(_nonce(prefix, n, True), cur, _aad(link_id, name, n))


def open_sealed(
    private: X25519PrivateKey, label: bytes, link_id: str, name: str, f
) -> Iterator[bytes]:
    """The plain bytes, chunk by chunk, each checked before it is given out. A file cut off
    after a whole chunk is caught at its end: no chunk carried the last flag."""
    head = f.read(HEADER)
    if len(head) != HEADER or head[:4] != MAGIC:
        raise SealError("not a sealed file")
    eph = X25519PublicKey.from_public_bytes(head[4:36])
    salt, prefix = head[36:68], head[68:75]
    (size,) = struct.unpack(">I", head[75:79])
    if size != CHUNK:
        raise SealError("an unknown chunk size")
    aead = _key(private.exchange(eph), salt, label)
    n = 0
    block = f.read(CHUNK + TAG)
    while True:
        nxt = f.read(CHUNK + TAG) if len(block) == CHUNK + TAG else b""
        last = not nxt
        try:
            plain = aead.decrypt(_nonce(prefix, n, last), block, _aad(link_id, name, n))
        except InvalidTag:
            raise SealError("a chunk fails its check: the file was changed or cut off") from None
        yield plain
        if last:
            return
        n, block = n + 1, nxt


def write(path: Path, pieces: Iterable[bytes]) -> int:
    """Written under a temporary name, synced to disk and renamed (S11.9.6.6). Returns the
    bytes written."""
    tmp = path.with_name(path.name + ".tmp")
    total = 0
    with open(tmp, "wb") as f:
        for p in pieces:
            f.write(p)
            total += len(p)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)
    return total
