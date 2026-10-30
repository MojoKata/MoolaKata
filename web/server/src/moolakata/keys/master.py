"""The three levels of keys (requirements S15.3).

The **master key** (128 bits) is the recovery phrase, never stored: an admin enters it when the
server starts (S15.4). It wraps one thing: the **data key** (256 bits), kept wrapped in the
data directory's `keyring`, so it travels with every backup and copy. From the data key
HKDF-SHA256 derives the database key, the receipts key pair and the secrets key, each under
its own label. The master key is held only while it unwraps or wraps; the data keys for the
server's lifetime.
"""

import base64
import datetime as dt
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .. import clock
from ..config import Config, RefuseStart

KEY_BYTES = 16
DATA_KEY_BYTES = 32
KEYRING_FORMAT = "moolakata-keyring-1"


def hkdf(key: bytes, label: str, length: int = 32) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=None, info=label.encode()).derive(
        key
    )


def key_id(master: bytes) -> str:
    """The first 16 hex digits of SHA-256("moolakata key id" ‖ key) (S15.3.5)."""
    return hashlib.sha256(b"moolakata key id" + master).hexdigest()[:16]


def data_key_id(data_key: bytes) -> str:
    """The same for a data key: a keyring names which data key it wraps, so the running
    server knows which copies hold the data key it has (S15.7.1) without unwrapping them."""
    return hashlib.sha256(b"moolakata data key id" + data_key).hexdigest()[:16]


def fingerprint(master_or_id: bytes | str) -> str:
    """The short form shown in Settings and on the recovery sheet: mk-3f9a…c21e."""
    kid = master_or_id if isinstance(master_or_id, str) else key_id(master_or_id)
    return f"mk-{kid[:4]}…{kid[-4:]}"


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def _unb64(s: str) -> bytes:
    return base64.b64decode(s, validate=True)


def now() -> dt.datetime:
    return clock.now().replace(microsecond=0)


# ---------- the keyring: the wrapped data key ----------


@dataclass(frozen=True)
class Previous:
    """A master key this keyring was wrapped under before a rotation (S15.7.1): its id, so
    Settings can say which copies made before that date still open with its phrase."""

    master_id: str
    rotated: dt.datetime


@dataclass(frozen=True)
class Keyring:
    master_id: str
    master_created: dt.datetime
    data_key_created: dt.datetime
    nonce: bytes
    wrapped: bytes
    previous: tuple[Previous, ...] = ()
    data_key_id: str = ""

    def to_json(self) -> str:
        return (
            json.dumps(
                {
                    "format": KEYRING_FORMAT,
                    "masterKeyId": self.master_id,
                    "masterCreatedAt": self.master_created.isoformat(),
                    "dataKeyCreatedAt": self.data_key_created.isoformat(),
                    "nonce": _b64(self.nonce),
                    "wrapped": _b64(self.wrapped),
                    "dataKeyId": self.data_key_id,
                    "previous": [
                        {"masterKeyId": p.master_id, "rotatedAt": p.rotated.isoformat()}
                        for p in self.previous
                    ],
                },
                indent=2,
            )
            + "\n"
        )

    @staticmethod
    def from_json(text: str) -> Keyring:
        d = json.loads(text)
        if d.get("format") != KEYRING_FORMAT:
            raise ValueError("not a MoolaKata keyring")
        return Keyring(
            d["masterKeyId"],
            dt.datetime.fromisoformat(d["masterCreatedAt"]),
            dt.datetime.fromisoformat(d["dataKeyCreatedAt"]),
            _unb64(d["nonce"]),
            _unb64(d["wrapped"]),
            tuple(
                Previous(p["masterKeyId"], dt.datetime.fromisoformat(p["rotatedAt"]))
                for p in d.get("previous", [])
            ),
            d.get("dataKeyId", ""),
        )


def _aad(master_id: str) -> bytes:
    return b"moolakata keyring|" + master_id.encode()


def wrap(
    master: bytes,
    data_key: bytes,
    master_created: dt.datetime,
    data_key_created: dt.datetime,
    previous: tuple[Previous, ...] = (),
) -> Keyring:
    nonce = os.urandom(12)
    mid = key_id(master)
    sealed = AESGCM(hkdf(master, "moolakata master")).encrypt(nonce, data_key, _aad(mid))
    return Keyring(
        mid, master_created, data_key_created, nonce, sealed, previous, data_key_id(data_key)
    )


def rotated(ring: Keyring, data_key: bytes, new_master: bytes, at: dt.datetime) -> Keyring:
    """The same data key wrapped under a new master key, the old one recorded (S15.7.1)."""
    return wrap(
        new_master,
        data_key,
        at,
        ring.data_key_created,
        (*ring.previous, Previous(ring.master_id, at)),
    )


def unwrap(master: bytes, ring: Keyring) -> bytes:
    if key_id(master) != ring.master_id:
        raise ValueError(
            f"the data key was wrapped by {fingerprint(ring.master_id)}, not by "
            f"{fingerprint(master)}"
        )
    try:
        return AESGCM(hkdf(master, "moolakata master")).decrypt(
            ring.nonce, ring.wrapped, _aad(ring.master_id)
        )
    except InvalidTag:
        raise ValueError("the master key does not unwrap the data key") from None


def write_keyring(path: Path, ring: Keyring, owner: int | None = None) -> None:
    """Replace the keyring atomically: written beside it, synced, then renamed."""
    tmp = path.with_name(path.name + ".new")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(ring.to_json())
        f.flush()
        os.fsync(f.fileno())
    if owner is not None:
        os.chown(tmp, owner, owner)
    os.replace(tmp, path)


def create_keyring(config: Config, master: bytes) -> Keyring:
    """A new server's keyring: a new data key wrapped under the master key (S15.4.4). The
    welcome makes one; so does a dev server, and a test."""
    if config.keyring_path.exists():
        raise RefuseStart(f"{config.keyring_path} already exists: this data directory has a key")
    refuse_a_database_without_its_keyring(config)
    config.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    at = now()
    ring = wrap(master, new_data_key(), at, at)
    write_keyring(config.keyring_path, ring)
    return ring


def read_keyring(path: Path) -> Keyring:
    try:
        return Keyring.from_json(path.read_text())
    except FileNotFoundError:
        raise RefuseStart(
            f"the keyring {path} is missing; restore it from a backup, or, on a new server, "
            "empty the data directory and open the page, whose welcome makes the key"
        ) from None
    except (ValueError, KeyError) as e:
        raise RefuseStart(f"the keyring {path} cannot be read: {e}") from None


def refuse_a_database_without_its_keyring(config: Config) -> None:
    """A database whose keyring is gone opens with no key made now, so the welcome may not
    make one for it: the start is refused (S15.4.5)."""
    if config.db_path.exists() and not config.keyring_path.exists():
        raise RefuseStart(
            f"{config.db_path} has no keyring beside it: bring its own back with `moolakata db "
            f"restore <backup>`, or, on a new server, empty {config.data_dir} to start again"
        )


# ---------- what the data key gives ----------


@dataclass(frozen=True)
class DataKeys:
    """The keys derived from the data key (S15.3.2), held for the server's lifetime."""

    database: bytes
    receipts: X25519PrivateKey
    secrets: bytes

    @staticmethod
    def derive(data_key: bytes) -> DataKeys:
        return DataKeys(
            database=hkdf(data_key, "moolakata database"),
            receipts=X25519PrivateKey.from_private_bytes(hkdf(data_key, "moolakata receipts")),
            secrets=hkdf(data_key, "moolakata secrets"),
        )

    @property
    def sqlcipher_key(self) -> str:
        return f"x'{self.database.hex()}'"


@dataclass(frozen=True)
class Unlocked:
    """What the server holds once unlocked: never the master key. The raw data key stays so
    the running server can re-wrap it under a new phrase (rotation, S15.7.1)."""

    master_id: str
    ring: Keyring
    keys: DataKeys
    data_key: bytes = b""


class WrongPhrase(ValueError):
    """The phrase is a valid one, but not the key that wrapped this keyring."""


def unlock_keys(config: Config, master: bytes) -> Unlocked:
    """At unlock: unwrap the data key from the keyring with the phrase's key. The master key
    is used here and nowhere kept."""
    ring = read_keyring(config.keyring_path)
    try:
        data_key = unwrap(master, ring)
    except ValueError as e:
        raise WrongPhrase(str(e)) from None
    return Unlocked(key_id(master), ring, DataKeys.derive(data_key), data_key)


def new_data_key() -> bytes:
    return os.urandom(DATA_KEY_BYTES)


def new_master() -> bytes:
    return os.urandom(KEY_BYTES)
