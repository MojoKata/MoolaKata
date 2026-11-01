"""This server's link key (requirements S11.1.3): an Ed25519 key pair made the first time it is
needed. The private half is a sealed secret (S14.4); the public half and its fingerprint are
what a peer checks."""

import base64
import hashlib

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from ..store.repos import secrets as secret_repo

SECRET = ("Setting", "link", "privateKey")


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def raw_public(key: Ed25519PublicKey) -> bytes:
    return key.public_bytes(Encoding.Raw, PublicFormat.Raw)


def fingerprint(public: bytes) -> str:
    """The full fingerprint a link code carries: SHA-256 of the raw public key, in hex."""
    return hashlib.sha256(public).hexdigest()


def short(fp: str) -> str:
    """The form shown to admins to compare: four groups of four."""
    return " ".join(fp[i : i + 4] for i in range(0, 16, 4))


def private_key(s, secrets_key: bytes, by: str | None = None) -> Ed25519PrivateKey:
    """This server's link key, made and sealed the first time."""
    raw = secret_repo.use(s, secrets_key, *SECRET)
    if raw is None:
        key = Ed25519PrivateKey.generate()
        secret_repo.put(
            s,
            secrets_key,
            *SECRET,
            b64(key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())),
            by,
        )
        s.flush()
        return key
    return Ed25519PrivateKey.from_private_bytes(unb64(raw))


def signing_key(srv) -> Ed25519PrivateKey:
    """The link key, to sign with: opened in a read transaction, made in a write one only the
    first time (S13.7.5.4: a call takes no write lock before it is checked)."""
    with srv.db.read(unscoped="links.keys: signing key") as s:
        raw = secret_repo.use(s, srv.keys.secrets, *SECRET)
    if raw is not None:
        return Ed25519PrivateKey.from_private_bytes(unb64(raw))
    with srv.db.tx(unscoped="links.keys: signing key") as s:
        return private_key(s, srv.keys.secrets)


def own_public(srv) -> tuple[bytes, str]:
    """The link key's public half and its fingerprint, held once worked out: a call is checked
    against them without opening the private key."""
    held = getattr(srv, "link_public", None)
    if held is None:
        public = raw_public(signing_key(srv).public_key())
        held = srv.link_public = (public, fingerprint(public))
    return held


def public_of(s, secrets_key: bytes) -> bytes:
    return raw_public(private_key(s, secrets_key).public_key())


def direction(sender_fp: str, receiver_fp: str) -> str:
    """What a sealed change or receipt's associated data names as its link: the sending and
    receiving servers' fingerprints, which both sides know, so a file sealed for one direction
    or one link opens for no other."""
    return f"{sender_fp}>{receiver_fp}"
