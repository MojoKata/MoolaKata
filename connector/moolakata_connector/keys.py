"""The connector's keys (requirements S18.4.2, S18.4.5), made at pairing: a status key
(Ed25519) kept here, beside the vault, which signs only a report that the connector is locked
and its `unpaired`; an action key (Ed25519) that signs every other call, and a sealing key
(X25519) that credentials are sealed to, both with their private halves in the vault
(`vault.py`) and their public halves here. With them, the server it is paired with: its
address, its link key's fingerprint, and, when its certificate is its own, the fingerprint of
that certificate's key (and the next one, once announced). This file holds nothing that opens a
credential, and nothing that does more than say the connector is locked."""

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def fingerprint(public: bytes) -> str:
    return hashlib.sha256(public).hexdigest()


def short(fp: str) -> str:
    return " ".join(fp[i : i + 4] for i in range(0, 16, 4))


@dataclass
class Pairing:
    address: str  # MoolaKata's address, from the pairing code
    server_fp: str  # its link key's fingerprint, whole
    status: Ed25519PrivateKey  # signs only "locked" and `unpaired`
    action_public: bytes  # the private half is in the vault
    sealing_public: bytes  # the private half is in the vault
    # MoolaKata's own certificate's key, pinned from the code (None: a public certificate,
    # verified against the system's roots), and the next one it announced (protocol §1.2).
    cert: str | None = None
    cert_next: str | None = None

    def pins(self) -> frozenset[str] | None:
        if self.cert is None:
            return None
        return frozenset(x for x in (self.cert, self.cert_next) if x)

    @property
    def status_public(self) -> bytes:
        return self.status.public_key().public_bytes_raw()

    @property
    def fingerprint(self) -> str:
        """The connector's fingerprint, the one an admin compares and confirms: its action
        key's (S18.4.2)."""
        return fingerprint(self.action_public)


def load(path: Path) -> Pairing | None:
    try:
        d = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    return Pairing(
        d["address"],
        d["serverFingerprint"],
        Ed25519PrivateKey.from_private_bytes(unb64(d["status"])),
        unb64(d["actionPublic"]),
        unb64(d["sealingPublic"]),
        d.get("certificate"),
        d.get("certificateNext"),
    )


def new_sealing_key() -> tuple[bytes, bytes]:
    """A sealing key pair as raw bytes: (private, for the vault; public, for MoolaKata)."""
    k = X25519PrivateKey.generate()
    return k.private_bytes_raw(), k.public_key().public_bytes_raw()


def new_action_key() -> tuple[bytes, bytes]:
    """An action key pair as raw bytes: (private, for the vault; public, for MoolaKata)."""
    k = Ed25519PrivateKey.generate()
    return k.private_bytes_raw(), k.public_key().public_bytes_raw()


def make(
    address: str,
    server_fp: str,
    action_public: bytes,
    sealing_public: bytes,
    cert: str | None = None,
) -> Pairing:
    """A new status key for a new pairing, in memory: saved only once MoolaKata has taken it,
    so a pairing that fails leaves the working one as it was (S18.4.2)."""
    return Pairing(
        address, server_fp, Ed25519PrivateKey.generate(), action_public, sealing_public, cert
    )


def save(path: Path, p: Pairing) -> None:
    """Written to a temporary file, synced and renamed over the old one: a crash leaves one
    pairing or the other, never half of one."""
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(
            {
                "address": p.address,
                "serverFingerprint": p.server_fp,
                "status": b64(p.status.private_bytes_raw()),
                "actionPublic": b64(p.action_public),
                "sealingPublic": b64(p.sealing_public),
                "certificate": p.cert,
                "certificateNext": p.cert_next,
            },
            f,
        )
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def forget(path: Path) -> None:
    if path.exists():
        path.unlink()
