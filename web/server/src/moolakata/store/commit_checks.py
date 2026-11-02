"""Checks every write transaction runs once its changes are in, before it commits (the filed
tax years walk, decision 1): each registered by the module that owns its rule, so a new way of
writing is checked without remembering to (`taxes.closed`)."""

from collections.abc import Callable
from contextvars import ContextVar

from sqlalchemy.orm import Session

# The questions a request confirmed by its header (`HEADER`, a comma-separated list of codes):
# a route outside the save answers a check's question this way, the browser retrying the
# request with it once the person confirms (decision 1 of the filed tax years walk).
HEADER = "x-moolakata-confirm"
confirmed: ContextVar[frozenset[str]] = ContextVar("confirmed", default=frozenset())

CHECKS: list[Callable[[Session], None]] = []


def register(fn: Callable[[Session], None]) -> Callable[[Session], None]:
    CHECKS.append(fn)
    return fn


def run(s: Session) -> None:
    s.flush()
    for fn in CHECKS:
        fn(s)


def notes(s: Session) -> dict:
    """What the checks note of a write as it goes, kept on its connection so the server's work
    inside it (`scoping.as_server`, a session of its own on the same connection) is noted too."""
    return s.connection().info.setdefault("commit_checks", {})


def reset(s: Session) -> None:
    """A write begins with nothing noted (a pooled connection keeps its info)."""
    s.connection().info.pop("commit_checks", None)
