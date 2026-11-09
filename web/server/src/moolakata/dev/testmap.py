"""The mutation baseline's test map (S17.5.12): a pytest plugin that, under `coverage run`,
measures each test's setup, call and teardown in a context named by its test file, so
`web/dev.sh mutate testmap` can name the test files that reach each module. A route module is
reached through HTTP, not imported, so the files that import it are not enough.

    coverage run -m pytest -p moolakata.dev.testmap ...
"""

import coverage
import pytest


def _switch(item: pytest.Item) -> None:
    cov = coverage.Coverage.current()
    if cov is not None:
        cov.switch_context(item.nodeid.split("::")[0])


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    _switch(item)


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_call(item: pytest.Item) -> None:
    _switch(item)


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_teardown(item: pytest.Item) -> None:
    _switch(item)
