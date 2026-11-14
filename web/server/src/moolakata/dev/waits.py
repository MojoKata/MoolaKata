"""How a test waits (requirements S17.5): for a condition or an event, with a generous timeout,
since a spurious failure costs far more than a real one that is slow to show; for a length of
time only to see that nothing happens, and then it says why. These are the tests' only waits:
`tests/test_waits.py` fails on a sleep anywhere else in them, and on an `idle` without its
reason written out."""

import asyncio
import time

# Long enough for a busy runner; a real failure is slower to show, never missed.
TIMEOUT = 30.0
STEP = 0.05


def _wait(check, pause, timeout: float, what: str) -> None:
    end = time.monotonic() + timeout
    while not check():
        if time.monotonic() > end:
            raise AssertionError(f"never true in {timeout:g} s: {what}")
        pause()


def until(page, cond, timeout: float = TIMEOUT, what: str = "") -> None:
    """Wait until a condition holds on a page: an expression, polled from outside the page (the
    app's CSP refuses a string evaluated inside it), or a check of the test's own. Between
    tries Playwright runs, so a route the test holds is answered meanwhile."""
    check = (lambda: page.evaluate(cond)) if isinstance(cond, str) else cond
    _wait(check, lambda: page.wait_for_timeout(STEP * 1000), timeout, what or str(cond))


def eventually(cond, timeout: float = TIMEOUT, what: str = "") -> None:
    """Wait until `cond()` holds, away from a page: a server up, a job done, a process ready."""
    _wait(cond, lambda: time.sleep(STEP), timeout, what or getattr(cond, "__name__", "?"))


async def eventually_async(cond, timeout: float = TIMEOUT, what: str = "") -> None:
    """`eventually`, in a test's event loop: the loop runs between tries."""
    end = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > end:
            raise AssertionError(f"never true in {timeout:g} s: {what}")
        await asyncio.sleep(STEP)


async def turn() -> None:
    """Let the event loop run what is ready (a task just created starts), waiting for nothing."""
    await asyncio.sleep(0)


def idle(seconds: float, *, why: str, page=None) -> None:
    """Let time pass, for a test that checks nothing happens meanwhile (no dialog opens, a card
    stays open) or for a pace that is itself under test (a peer that answers slowly). `why`
    says which; with a page, Playwright runs meanwhile."""
    if not why.strip() or seconds <= 0:
        raise ValueError("idle takes a time and why it waits for time, not a condition")
    if page is None:
        time.sleep(seconds)
    else:
        page.wait_for_timeout(seconds * 1000)
