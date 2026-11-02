"""A budget's month figures, kept once worked out (requirements S7.3.10), under the data version
they were worked out from (docs/schema.md §8). The version is read in the same transaction as
the figures' data, so a month is never kept under a version newer than its data; any write to
what figures come from moves the version on, and a month worked out before it is worked out
again. Only a read's figures are kept: a write's could still be rolled back. Refresh forgets a
budget's months at once.

`CHECK` (on in the tests) works a month out again on every hit and fails if the kept figures
differ, so every test that reads a month also proves the cache returns what the data says.
"""

import itertools
import threading
import weakref
from collections import OrderedDict

from sqlalchemy.orm import Session

from ..store import data_version

KEEP = 512  # months kept, the least recently used dropped first
CHECK = False

_lock = threading.Lock()
_months: OrderedDict = OrderedDict()
# Each database opened in this process, numbered as first seen, so two never share a key even
# when their versions agree.
_opened: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_numbers = itertools.count(1)


class Stale(AssertionError):
    """A kept month differs from the one its data gives (CHECK)."""


def _database(s: Session) -> int:
    engine = s.get_bind().engine
    with _lock:
        n = _opened.get(engine)
        if n is None:
            n = _opened[engine] = next(_numbers)
        return n


def month(s: Session, key: tuple, work):
    """The month `key` names: kept, or worked out by `work()` and kept when the session is a
    read."""
    full = (_database(s), data_version.read(s), *key)
    with _lock:
        hit = _months.get(full)
        if hit is not None:
            _months.move_to_end(full)
    if hit is not None:
        if CHECK:
            fresh = work()
            if fresh != hit:
                raise Stale(f"the kept month {key} differs from its data")
        return hit
    value = work()
    if data_version.read_only(s):
        with _lock:
            _months[full] = value
            while len(_months) > KEEP:
                _months.popitem(last=False)
    return value


def forget(budget_id: str) -> None:
    """Refresh: the budget's months are worked out again on their next read."""
    with _lock:
        for k in [k for k in _months if k[2] == budget_id]:
            del _months[k]


def clear() -> None:
    with _lock:
        _months.clear()
