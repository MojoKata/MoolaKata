"""Loaded into mutmut's pytest runs by `mutate` (`-p moolakata.dev.mutant_name`): a change's
worker takes the name `mutmut: <change>`, as mutmut's fork mode names it and its forkserver
mode does not, so `mutate`'s watcher finds each change's worker by its name."""

import os


def pytest_configure(config) -> None:
    name = os.environ.get("MUTANT_UNDER_TEST", "")
    if "__mutmut_" in name:  # not the stats ("stats"), the forced failure ("fail") or the clean run
        title(f"mutmut: {name}")


def title(text: str) -> None:
    """The process's name, by mutmut's own means (the copy installs mutmut; setup doesn't)."""
    from mutmut.utils.safe_setproctitle import safe_setproctitle

    safe_setproctitle(text)
