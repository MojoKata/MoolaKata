"""Linked copies (requirements S11.9): what a link brings in, kept apart in its own folder and
SQLCipher database under the link's own access key.

1. The **copy key** is 16 random bytes, shown once as 12 BIP39 words (S11.9.2) and never stored.
   HKDF-SHA256 derives from it the **database key** (SQLCipher's raw key) and the **copy's
   private key** (X25519), whose public half is the only trace of it in the main database.
2. **Unlocking** (S11.9.3) checks the words' checksum and that they derive the stored public
   key, then holds the key in memory for the whole server. Five wrong tries in a row make that
   user wait 15 minutes; a copy takes at most 20 tries an hour from everyone together.
3. **Locking** (S11.9.4) closes the copy's connections and overwrites the key's bytes: when it
   has gone unused for the time Settings › Linked Servers sets, at Lock now, and at restart
   (the key only ever lived in memory)."""

import datetime as dt
import shutil
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from sqlalchemy import Engine

from ..keys import phrase
from ..store.db import HeldKey, make_engine
from . import copydb
from .keys import b64

DB_LABEL = b"moolakata link database"
PRIVATE_LABEL = b"moolakata link private key"
WRONG_IN_A_ROW = 5
WAIT_SECONDS = 15 * 60
PER_HOUR = 20


class CopyError(Exception):
    def __init__(self, code: str, message: str, wait: float = 0):
        super().__init__(message)
        self.code = code
        self.message = message
        self.wait = wait


def _derive(copy_key: bytes, label: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=label).derive(copy_key)


def private_key(copy_key: bytes) -> X25519PrivateKey:
    return X25519PrivateKey.from_private_bytes(_derive(copy_key, PRIVATE_LABEL))


def public_of(copy_key: bytes) -> str:
    pub = private_key(copy_key).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return b64(pub)


# Each link's copy lives in a folder with a random name, never the link's id, which would
# date the link on disk (schema.md §2.5). The names come from the Link rows at unlock and from
# `Copies.create`, which makes them; a link with no name yet falls back to its id.
NAMES: dict[str, str] = {}


def folder(data_dir: Path, link_id: str) -> Path:
    return data_dir / "links" / NAMES.get(link_id, link_id)


def new_name() -> str:
    import secrets

    return secrets.token_hex(12)


def new_key() -> tuple[bytes, list[str]]:
    import secrets

    key = secrets.token_bytes(16)
    return key, phrase.to_words(key)


@dataclass
class Open:
    key: bytearray
    engine: Engine
    by: str  # the user who unlocked it
    at: dt.datetime
    used: float  # monotonic time of the last read for a person
    db_key: HeldKey | None = None  # the database's key, overwritten at the release


@dataclass
class Copies:
    """The unlocked copies, in memory only (S11.9.3, S11.9.4)."""

    clock: object = time.monotonic
    open: dict[str, Open] = field(default_factory=dict)
    wrong: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))
    waiting: dict[tuple[str, str], float] = field(default_factory=dict)
    tries: dict[str, deque] = field(default_factory=lambda: defaultdict(deque))
    lock: threading.RLock = field(default_factory=threading.RLock)

    def _check_limits(self, link_id: str, user_id: str) -> None:
        now = self.clock()
        until = self.waiting.get((link_id, user_id), 0)
        if until > now:
            raise CopyError(
                "too-many-wrong",
                "Five wrong tries in a row: wait 15 minutes before trying again.",
                until - now,
            )
        q = self.tries[link_id]
        while q and now - q[0] >= 3600:
            q.popleft()
        if len(q) >= PER_HOUR:
            raise CopyError(
                "too-many-tries",
                "This copy has had 20 tries in the last hour: try again later.",
                3600 - (now - q[0]),
            )
        q.append(now)

    def unlock(
        self, data_dir: Path, link_id: str, public: str, words: str, user_id: str, at: dt.datetime
    ) -> Open:
        with self.lock:
            # The words are checked even when someone else has the copy open already: an
            # unlock is recorded only for the words (S11.9.4).
            self._check_limits(link_id, user_id)
            try:
                key = phrase.from_words(words)
            except phrase.PhraseError:
                key = None
            if key is None or public_of(key) != public:
                n = self.wrong[(link_id, user_id)] = self.wrong[(link_id, user_id)] + 1
                if n >= WRONG_IN_A_ROW:
                    self.waiting[(link_id, user_id)] = self.clock() + WAIT_SECONDS
                    self.wrong[(link_id, user_id)] = 0
                raise CopyError("words-wrong", "Those aren't this copy's words.")
            self.wrong.pop((link_id, user_id), None)
            if link_id in self.open:
                self.open[link_id].used = self.clock()
                return self.open[link_id]
            return self._open(data_dir, link_id, key, user_id, at)

    def _open(self, data_dir, link_id, key: bytes, user_id: str, at) -> Open:
        path = folder(data_dir, link_id)
        path.mkdir(parents=True, exist_ok=True)
        (path / "receipts").mkdir(exist_ok=True)
        (path / "inbox").mkdir(exist_ok=True)
        db_key = HeldKey(_derive(key, DB_LABEL))
        engine = make_engine(path / "shared.db", db_key)
        copydb.upgrade(engine)
        o = Open(bytearray(key), engine, user_id, at, self.clock(), db_key)
        self.open[link_id] = o
        return o

    def create(self, data_dir: Path, link_id: str, user_id: str, at) -> tuple[str, list[str], str]:
        """A new copy key: the copy made empty, in a folder with a new random name, then
        locked, since its maker may not be someone its shares name. Returns its public key,
        the words, shown once, and the folder's name, for the Link row."""
        key, words = new_key()
        with self.lock:
            self.release(link_id)
            shutil.rmtree(folder(data_dir, link_id), ignore_errors=True)
            NAMES[link_id] = new_name()
            self._open(data_dir, link_id, key, user_id, at)
            self.release(link_id)
        return public_of(key), words, NAMES[link_id]

    def get(self, link_id: str, for_person: bool = True) -> Open | None:
        with self.lock:
            o = self.open.get(link_id)
            if o is not None and for_person:
                o.used = self.clock()
            return o

    def release(self, link_id: str) -> bool:
        """Close the copy's connections and overwrite the key's bytes."""
        with self.lock:
            o = self.open.pop(link_id, None)
            if o is None:
                return False
            o.engine.dispose()
            if o.db_key is not None:
                o.db_key.release()
            for i in range(len(o.key)):
                o.key[i] = 0
            return True

    def sweep(self, minutes: int) -> list[str]:
        """Lock every copy unused for longer than this; returns the links locked."""
        now = self.clock()
        with self.lock:
            stale = [k for k, o in self.open.items() if now - o.used > minutes * 60]
        return [k for k in stale if self.release(k)]

    def locks_in(self, link_id: str, minutes: int) -> float | None:
        o = self.open.get(link_id)
        return None if o is None else max(0.0, minutes * 60 - (self.clock() - o.used))

    def reset(self, data_dir: Path, link_id: str) -> None:
        with self.lock:
            self.release(link_id)
            shutil.rmtree(folder(data_dir, link_id), ignore_errors=True)
