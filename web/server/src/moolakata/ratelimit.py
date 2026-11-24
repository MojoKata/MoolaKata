"""Rate limits (requirements S13.7.5), answered with 429 and Retry-After. Counters live in
memory: they are work state, not records (schema.md §4.4), and a restart clears them."""

import ipaddress
import math
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable

from .errors import Problem


class Window:
    """At most `limit` events per `seconds` for each key. A key is forgotten once its events
    have lapsed, so keys that are never seen again (addresses, sessions) don't pile up."""

    def __init__(self, limit: int, seconds: float, clock: Callable[[], float] = time.monotonic):
        self.limit = limit
        self.seconds = seconds
        self._clock = clock
        self._seen: dict[str, deque] = defaultdict(deque)
        self._swept = clock()
        self._lock = threading.Lock()

    def __len__(self) -> int:
        """The keys held."""
        with self._lock:
            return len(self._seen)

    def _trim(self, q: deque, now: float) -> None:
        while q and now - q[0] >= self.seconds:
            q.popleft()

    def _sweep(self, now: float) -> None:
        # Once a window: each pass is over every key, so it costs no more than the hits since.
        if now - self._swept < self.seconds:
            return
        self._swept = now
        for key in [k for k, q in self._seen.items() if not q or now - q[-1] >= self.seconds]:
            del self._seen[key]

    def hit(self, key: str) -> float:
        """Count one event; returns 0, or the seconds to wait when over the limit."""
        with self._lock:
            now = self._clock()
            self._sweep(now)
            q = self._seen[key]
            self._trim(q, now)
            if len(q) >= self.limit:
                return self.seconds - (now - q[0])
            q.append(now)
            return 0.0

    def wait(self, key: str) -> float:
        """The seconds to wait before an event would be counted, without counting one."""
        with self._lock:
            now = self._clock()
            q = self._seen.get(key)
            if not q:
                return 0.0
            self._trim(q, now)
            return self.seconds - (now - q[0]) if len(q) >= self.limit else 0.0

    def count(self, key: str) -> int:
        with self._lock:
            q = self._seen.get(key)
            if not q:
                return 0
            self._trim(q, self._clock())
            return len(q)

    def clear(self, key: str) -> None:
        with self._lock:
            self._seen.pop(key, None)

    def check(self, key: str, what: str) -> None:
        wait = self.hit(key)
        if wait:
            raise too_many(wait, what)


def address_key(host: str | None) -> str:
    """An address as a limit counts it: an IPv6 one by its /64, which one household is given
    whole (S13.7.5.1)."""
    try:
        ip = ipaddress.ip_address(host or "")
    except ValueError:
        return host or "-"
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            return str(ip.ipv4_mapped)
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


def too_many(wait: float, what: str) -> Problem:
    return Problem(
        429,
        "rate-limited",
        f"Too many {what}. Try again in a moment.",
        headers={"Retry-After": str(max(1, math.ceil(wait)))},
    )


# The longest login that can name a user: an email's limit; a username is shorter (S10.1).
LOGIN_MAX = 254


class SignInGuard:
    """Ten failures in 15 minutes lock the **address** they came from for 15 minutes, an IPv6
    one by its /64, and a username that keeps failing is **slowed**, never locked, so nobody can
    lock an admin out by typing wrong passwords (S13.7.5.1, S10.1). Lockout length and threshold
    come from Settings. A two-step sign-in is checked one code at a time, and ends after five
    wrong codes, so the password is needed again (S10.1.6.3). What has lapsed is forgotten,
    and a login longer than any can be is never kept, so a scan of made-up usernames doesn't
    grow the server's memory (S13.7.5.5)."""

    CODE_TRIES = 5
    WINDOW = 15 * 60

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._failures: dict[str, deque] = defaultdict(deque)  # by address
        self._by_user: dict[str, deque] = defaultdict(deque)
        self._locked_until: dict[str, float] = {}  # by address
        # Wrong codes and when the first came, by pending sign-in, which lasts five minutes.
        self._codes: dict[str, tuple[int, float]] = {}
        self._checking: set[str] = set()  # the pending sign-ins whose code is being checked
        self._swept = clock()
        self._lock = threading.Lock()

    def _trim(self, q: deque, now: float) -> None:
        while q and now - q[0] >= self.WINDOW:
            q.popleft()

    def _sweep(self, now: float) -> None:
        # Once a window, as Window's: failures that no longer count, lockouts that have
        # ended and the codes of pending sign-ins long expired.
        if now - self._swept < self.WINDOW:
            return
        self._swept = now
        for held in (self._failures, self._by_user):
            for key in [k for k, q in held.items() if not q or now - q[-1] >= self.WINDOW]:
                del held[key]
        for key in [k for k, until in self._locked_until.items() if until <= now]:
            del self._locked_until[key]
        for key in [k for k, (_, at) in self._codes.items() if now - at >= self.WINDOW]:
            del self._codes[key]

    def held(self) -> dict[str, int]:
        """How many of each it holds."""
        with self._lock:
            return {
                "addresses": len(self._failures),
                "usernames": len(self._by_user),
                "locks": len(self._locked_until),
                "codes": len(self._codes),
            }

    def locked(self, address: str) -> float:
        """Seconds the address stays locked, or 0."""
        with self._lock:
            until = self._locked_until.get(address_key(address), 0)
            left = until - self._clock()
            return left if left > 0 else 0.0

    def delay(self, username: str, address: str) -> float:
        """A pause before answering for a username that keeps failing, from anywhere: half a
        second per failure past the third, 0.5 × (failures − 3), up to five seconds
        (S13.7.5.1)."""
        with self._lock:
            q = self._by_user.get(username.lower())
            if not q:
                return 0.0
            self._trim(q, self._clock())
            n = len(q)
        return 0.0 if n <= 3 else min(5.0, 0.5 * (n - 3))

    def succeeded(self, username: str) -> None:
        """A sign-in: the username's failures are forgotten, so it is no longer slowed."""
        with self._lock:
            self._by_user.pop(username.lower(), None)

    def failed(
        self, username: str, address: str, threshold: int = 10, lock_minutes: int = 15
    ) -> bool:
        """Record a failure; True when it locks the address. A login too long to name anyone
        counts against the address alone."""
        with self._lock:
            now = self._clock()
            self._sweep(now)
            if len(username) <= LOGIN_MAX:
                u = self._by_user[username.lower()]
                self._trim(u, now)
                u.append(now)
            return self._count(address, now, threshold, lock_minutes)

    def asked(self, address: str, threshold: int = 10, lock_minutes: int = 15) -> bool:
        """A password-reset request, counted against its address alone, as a failure is
        (S13.7.5.1): it names no username to slow. True when it locks the address."""
        with self._lock:
            now = self._clock()
            self._sweep(now)
            return self._count(address, now, threshold, lock_minutes)

    def _count(self, address: str, now: float, threshold: int, lock_minutes: int) -> bool:
        address = address_key(address)
        q = self._failures[address]
        self._trim(q, now)
        q.append(now)
        if len(q) >= threshold:
            self._locked_until[address] = now + lock_minutes * 60
            q.clear()
            return True
        return False

    def checking(self, pending: str) -> bool:
        """Begin checking a code for a pending two-step sign-in; False while another of its
        codes is being checked."""
        with self._lock:
            if pending in self._checking:
                return False
            self._checking.add(pending)
            return True

    def checked(self, pending: str) -> None:
        with self._lock:
            self._checking.discard(pending)

    def code_wrong(self, pending: str) -> bool:
        """A wrong code for a pending sign-in; True once it has had its five, and ends."""
        with self._lock:
            now = self._clock()
            self._sweep(now)
            n, first = self._codes.get(pending, (0, now))
            if n + 1 >= self.CODE_TRIES:
                self._codes.pop(pending, None)
                return True
            self._codes[pending] = (n + 1, first)
            return False

    def code_done(self, pending: str) -> None:
        with self._lock:
            self._codes.pop(pending, None)
