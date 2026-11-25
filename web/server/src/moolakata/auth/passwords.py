"""Passwords (requirements S13.7.3): argon2id at 64 MiB, 3 passes, parallelism 1; the minimum
length Settings set, and no other rule than refusing the 100,000 most common passwords (the
UK NCSC's list, shipped with the app)."""

import gzip
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from ..ratelimit import too_many

COMMON_FILE = Path(__file__).with_name("common-passwords.txt.gz")
PARAMS = {"time_cost": 3, "memory_cost": 64 * 1024, "parallelism": 1, "type": Type.ID}
_hasher = PasswordHasher(**PARAMS)


def use_fast_hashing_for_tests() -> None:
    """Tests sign in hundreds of times; they trade the cost for speed. Never at run time."""
    global _hasher
    _hasher = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1, type=Type.ID)


# At most two hashes at once, 64 MiB each, so a burst of sign-ins can't take the server's
# memory; one past them waits a little, then is answered too many (S13.7.3).
AT_ONCE = 2
WAIT = 3.0
_slots = threading.BoundedSemaphore(AT_ONCE)


@contextmanager
def slot() -> Iterator[None]:
    """One of the hashes that may run at once, or 429 once none comes free in WAIT seconds."""
    if not _slots.acquire(timeout=WAIT):
        raise too_many(1, "passwords checked at once")
    try:
        yield
    finally:
        _slots.release()


@cache
def common() -> frozenset[str]:
    return frozenset(gzip.decompress(COMMON_FILE.read_bytes()).decode().split("\n")) - {""}


def problem(password: str, min_length: int) -> tuple[str, str] | None:
    """Why a new password is refused, as (code, message), or None."""
    if len(password) < min_length:
        return "password-too-short", f"Use at least {min_length} characters."
    if len(password) > 1024:
        return "password-too-long", "Use at most 1,024 characters."
    if password in common() or password.lower() in common():
        return "password-too-common", (
            "This password is on the list of the most common ones. Choose another."
        )
    return None


def hash_password(password: str) -> str:
    with slot():
        return _hasher.hash(password)


_DUMMY: list[str] = []


def verify(stored: str | None, password: str) -> bool:
    """Check a password; with no stored hash, spend the same time and fail, so a missing
    user can't be told from a wrong password by timing."""
    if not _DUMMY:
        _DUMMY.append(hash_password("moolakata timing dummy"))
    with slot():
        try:
            return _hasher.verify(stored or _DUMMY[0], password) and stored is not None
        except VerifyMismatchError, VerificationError, InvalidHashError:
            return False


@dataclass(frozen=True)
class Chosen:
    """A new password, judged by the rule and, when it passes, hashed before the write that
    keeps it, so a hash never holds up the server's one writer (S13.7.3): why it is refused,
    or its hash."""

    problem: tuple[str, str] | None
    hash: str | None = field(default=None, repr=False)


def choose(password: str, min_length: int) -> Chosen:
    """A new password judged and, if it passes, hashed; one refused is not hashed."""
    why = problem(password, min_length)
    return Chosen(why, None if why else hash_password(password))


def needs_rehash(stored: str) -> bool:
    return _hasher.check_needs_rehash(stored)
