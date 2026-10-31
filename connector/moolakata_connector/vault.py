"""The vault (requirements S18.3): every Connection's credentials, each bound to the host it
may be sent to (S18.7.3), and the sealing key that credentials are sealed to (S18.4.5), all
sealed with AES-256-GCM under a key derived from the 12 words, in one file. It opens only with
the words, which are never stored: the key stays in memory while the connector is unlocked, and
a restart locks it. Five wrong attempts in a row make the next wait 15 minutes."""

import hashlib
import json
import os
import time
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from . import words

FORMAT = "moolakata-connector-vault-1"
WAIT_AFTER = 5
WAIT_SECONDS = 15 * 60


class VaultError(Exception):
    """`kind` says what was wrong without the words: what a log may keep (S18.3.1)."""

    def __init__(self, message: str, kind: str = "refused"):
        super().__init__(message)
        self.kind = kind


def fingerprint(key: bytes) -> str:
    return hashlib.sha256(b"moolakata connector vault" + key).hexdigest()[:16]


def _aes(key: bytes) -> AESGCM:
    derived = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=b"moolakata connector vault key"
    ).derive(key)
    return AESGCM(derived)


class Vault:
    """The file on disk, and the key in memory while unlocked."""

    def __init__(self, path: Path):
        self.path = path
        self._key: bytes | None = None
        self._wrong = 0
        self._wait_until = 0.0

    # ----- making and opening -----

    def exists(self) -> bool:
        return self.path.exists()

    def create(self, key: bytes | None = None) -> list[str]:
        """A new key (random, or the one the words typed at `reset` give), the vault sealed
        empty under it; the words shown once."""
        if self.path.exists():
            raise VaultError(f"{self.path} already exists; `reset` replaces it")
        key = key or os.urandom(16)
        self._key = key
        self._write({"connections": {}, "sealing": None})
        return words.to_words(key)

    def reset(self, phrase: str | None = None) -> list[str]:
        """Lost words (S18.3.4): the vault deleted, a new one made under new words."""
        key = words.from_words(phrase) if phrase else None
        if self.path.exists():
            self.path.unlink()
        self._key = None
        return self.create(key)

    @property
    def locked(self) -> bool:
        return self._key is None

    def waiting(self) -> float:
        return max(0.0, self._wait_until - time.monotonic())

    def unlock(self, phrase: str) -> None:
        self._key = self._key_of(phrase)

    def check(self, phrase: str) -> None:
        """Whether these are the vault's words, changing nothing: what each action on the page
        asks first (S18.11.4). Wrong ones count toward the wait as at the unlock."""
        self._key_of(phrase)

    def _key_of(self, phrase: str) -> bytes:
        if self.waiting():
            raise VaultError(
                f"wait {int(self.waiting() // 60) + 1} minutes: too many wrong words", "waiting"
            )
        try:
            key = words.from_words(phrase)
        except words.PhraseError as e:
            self._wrong_one()
            # The message may name a mistyped word, for the person typing; the kind never does.
            raise VaultError(str(e), "not a valid phrase") from None
        stored = self._header()
        if stored["fingerprint"] != fingerprint(key):
            self._wrong_one()
            raise VaultError(
                "those words are a valid phrase, but not this vault's", "another vault's"
            )
        self._wrong = 0
        return key

    def _wrong_one(self) -> None:
        self._wrong += 1
        if self._wrong >= WAIT_AFTER:
            self._wait_until = time.monotonic() + WAIT_SECONDS
            self._wrong = 0

    def lock(self) -> None:
        if self._key is not None:
            self._key = bytes(len(self._key))  # overwritten, then released
        self._key = None

    def fingerprint(self) -> str | None:
        try:
            return self._header()["fingerprint"]
        except VaultError:
            return None

    # ----- the credentials -----

    def _header(self) -> dict:
        try:
            d = json.loads(self.path.read_text())
        except FileNotFoundError:
            raise VaultError("no vault: run `moolakata-connector init` first") from None
        except ValueError:
            raise VaultError(f"{self.path} is not a vault") from None
        if d.get("format") != FORMAT:
            raise VaultError(f"{self.path} is not a vault")
        return d

    def _read(self) -> dict:
        if self._key is None:
            raise VaultError("the vault is locked")
        d = self._header()
        try:
            plain = _aes(self._key).decrypt(
                bytes.fromhex(d["nonce"]), bytes.fromhex(d["sealed"]), d["fingerprint"].encode()
            )
        except InvalidTag, KeyError, ValueError:
            raise VaultError("the vault does not open: changed, or another vault's words") from None
        return json.loads(plain)

    def _write(self, content: dict) -> None:
        assert self._key is not None
        nonce = os.urandom(12)
        fp = fingerprint(self._key)
        sealed = _aes(self._key).encrypt(nonce, json.dumps(content).encode(), fp.encode())
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(
                {"format": FORMAT, "fingerprint": fp, "nonce": nonce.hex(), "sealed": sealed.hex()},
                f,
            )
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    def get(self, connection_id: str) -> dict | None:
        """The credentials, or None."""
        entry = self._read()["connections"].get(connection_id)
        return entry["credentials"] if entry else None

    def host(self, connection_id: str) -> str | None:
        """The host the credentials were bound to when filed (S18.7.3)."""
        entry = self._read()["connections"].get(connection_id)
        return entry.get("host") if entry else None

    def put(self, connection_id: str, credentials: dict, host: str | None = None, at=None) -> None:
        """File credentials, bound to the host they may be sent to: a driver with a host of
        its own binds none. `at`: when the owner sealed them, kept to refuse an older box."""
        content = self._read()
        held = content["connections"].get(connection_id) or {}
        at = at or held.get("sealedAt", 0)
        content["connections"][connection_id] = {"credentials": credentials, "host": host}
        content["connections"][connection_id]["sealedAt"] = at
        self._write(content)

    def sealed_at(self, connection_id: str) -> float:
        return (self._read()["connections"].get(connection_id) or {}).get("sealedAt", 0)

    def delete(self, connection_id: str) -> None:
        content = self._read()
        if content["connections"].pop(connection_id, None) is not None:
            self._write(content)

    def ids(self) -> list[str]:
        return sorted(self._read()["connections"])

    # ----- the sealing key -----

    def sealing_key(self) -> bytes | None:
        """The raw private sealing key, kept in the vault so a stolen volume can't open the
        boxes sealed to it (S18.4.5); None until a pairing made one."""
        raw = self._read().get("sealing")
        return bytes.fromhex(raw) if raw else None

    def keep_sealing_key(self, raw: bytes) -> None:
        content = self._read()
        content["sealing"] = raw.hex()
        self._write(content)
