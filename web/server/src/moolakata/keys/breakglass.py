"""The break-glass code (requirements S15.5.2): the way to rotate when the recovery phrase is
lost while the server runs. `moolakata keys break-glass`, run inside the server's container,
asks the running, unlocked server over its Unix socket for a code; an admin types it into
Settings › Key storage › Rotate in place of the current phrase. The code lasts 15 minutes and
is used once; only its hash is held, in memory, so a restart voids it. Whoever reaches the
socket of an unlocked server can already read its data key from memory, so the code gives
them nothing new (S15.7.1); it keeps the new phrase off the host's terminal and its logs."""

import datetime as dt
import hashlib
import hmac
import secrets
import threading
import time

from .. import clock

LIFE = 15 * 60
# Crockford's base32: no I, L, O or U to misread.
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _normal(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum()).removeprefix("BG")


def _hash(code: str) -> bytes:
    return hashlib.sha256(b"moolakata break-glass|" + _normal(code).encode()).digest()


class BreakGlass:
    """At most one code at a time: a new one replaces the last."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hash: bytes | None = None
        self._until = 0.0

    def issue(self) -> tuple[str, dt.datetime]:
        body = "".join(secrets.choice(ALPHABET) for _ in range(8))
        code = f"BG-{body[:4]}-{body[4:]}"
        with self._lock:
            self._hash, self._until = _hash(code), time.monotonic() + LIFE
        return code, clock.now() + dt.timedelta(seconds=LIFE)

    def use(self, code: str) -> bool:
        """Whether the code is the one on issue and unexpired; a right one is used up."""
        with self._lock:
            ok = (
                self._hash is not None
                and time.monotonic() < self._until
                and hmac.compare_digest(self._hash, _hash(code))
            )
            if ok:
                self._hash = None
            return ok
