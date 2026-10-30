"""Encrypted files (requirements S11.9.6, S9.2, S15.3.2): one streaming format, so a 25 MB
receipt is never held whole in memory.

    header  MKR1 · a one-time X25519 public key (32) · salt (32) · nonce prefix (7) ·
            chunk size (4, big-endian)
    chunks  each 64 KiB of plaintext sealed with AES-256-GCM (16-byte tag)

The file's key is HKDF-SHA256 over the X25519 exchange between the one-time key and the
receipts key, with the salt, under a label naming what it is. Each chunk's nonce is the prefix,
a 4-byte counter and a last-chunk flag, so a chunk can't be reordered, dropped or cut off
unnoticed; the associated data names the file and the chunk's number, so a file renamed or
copied onto another fails to open. This is the AES-GCM-HKDF streaming construction, built on
the `cryptography` library alone.
"""

import os
import struct
from collections.abc import Iterable, Iterator
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

MAGIC = b"MKR1"
CHUNK = 64 * 1024
TAG = 16
HEADER = len(MAGIC) + 32 + 32 + 7 + 4
RECEIPT = "moolakata receipt"


class FileError(ValueError):
    pass


def _raw(public: X25519PublicKey) -> bytes:
    return public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def _key(shared: bytes, salt: bytes, label: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=label.encode()).derive(shared)


def _nonce(prefix: bytes, counter: int, last: bool) -> bytes:
    return prefix + struct.pack(">I?", counter, last)


def _aad(name: str, counter: int) -> bytes:
    return f"{name}\x1f{counter}".encode()


def seal(
    chunks: Iterable[bytes], recipient: X25519PublicKey, name: str, label: str = RECEIPT
) -> Iterator[bytes]:
    """The encrypted file, piece by piece, from the plaintext in any sized pieces."""
    once = X25519PrivateKey.generate()
    salt, prefix = os.urandom(32), os.urandom(7)
    aes = AESGCM(_key(once.exchange(recipient), salt, label))
    yield MAGIC + _raw(once.public_key()) + salt + prefix + struct.pack(">I", CHUNK)
    buf = b""
    counter = 0
    for piece in chunks:
        buf += piece
        # A full chunk goes out only once more follows: the last one carries the flag, and
        # may be short (or empty, for an empty file).
        while len(buf) > CHUNK:
            yield aes.encrypt(_nonce(prefix, counter, False), buf[:CHUNK], _aad(name, counter))
            buf, counter = buf[CHUNK:], counter + 1
    yield aes.encrypt(_nonce(prefix, counter, True), buf, _aad(name, counter))


def open_stream(
    path: Path, key: X25519PrivateKey, name: str, label: str = RECEIPT
) -> Iterator[bytes]:
    """The plaintext of an encrypted file, chunk by chunk, each checked before it is given."""
    with open(path, "rb") as f:
        head = f.read(HEADER)
        if len(head) != HEADER or not head.startswith(MAGIC):
            raise FileError(f"{path.name} is not a MoolaKata encrypted file")
        public = X25519PublicKey.from_public_bytes(head[4:36])
        salt, prefix = head[36:68], head[68:75]
        size = struct.unpack(">I", head[75:79])[0]
        aes = AESGCM(_key(key.exchange(public), salt, label))
        counter = 0
        block = f.read(size + TAG)
        while True:
            following = f.read(size + TAG)
            last = not following
            try:
                yield aes.decrypt(_nonce(prefix, counter, last), block, _aad(name, counter))
            except InvalidTag:
                raise FileError(f"{path.name} does not open: changed, cut short or moved") from None
            if last:
                return
            block, counter = following, counter + 1


def write(path: Path, chunks: Iterable[bytes], recipient: X25519PublicKey, name: str) -> None:
    """Written under a temporary name, synced and renamed (S11.9.6.6), never changed after."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            for piece in seal(chunks, recipient, name):
                f.write(piece)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        # A source that fails part-way (a damaged file being re-encrypted, CR3-59) leaves no
        # half-written file behind.
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, path)
