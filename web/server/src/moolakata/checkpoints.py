"""Named points inside operations that write files or rows in more than one step (requirements
S17.5.10): a test sets a hook on one to run, right there, whatever could race the operation (a
background task's sweep, a second pull), so each race is reproduced at will rather than by
luck. Nothing happens at a point no test has hooked."""

from collections.abc import Callable

HOOKS: dict[str, Callable[[], None]] = {}


def checkpoint(name: str) -> None:
    hook = HOOKS.get(name)
    if hook is not None:
        hook()
