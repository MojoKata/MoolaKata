import json
import os
import re
import shutil
from decimal import Decimal
from pathlib import Path

import parts  # CI's parts, split by measured time (S17.10.1)
import pytest

# The browser tests' shared fixtures (S17.5.2), defined once for every module that uses them.
from browser import browser, household, served  # noqa: F401

# And the whole app's, on a seeded dev server (test_app.py, test_app_guides.py).
from devapp import dev_server, page  # noqa: F401
from fastapi.testclient import TestClient
from jscoverage import install as measure_the_browser_app

from moolakata import exactjson
from moolakata.app import Server, create_app
from moolakata.auth import passwords
from moolakata.auth import users as accounts
from moolakata.budgets import cache as month_cache
from moolakata.config import Config
from moolakata.keys import master
from moolakata.store import mapping
from moolakata.store.maintenance import open_store

measure_the_browser_app()
# The records are mapped before any test, as the server maps them when it starts: a test that
# builds a query on a fake session works alone as well as after one that opened a store.
mapping.map_all()
# Every kept budget month is worked out again on a hit and compared (S7.3.10): each test that
# reads a month twice also proves the cache answers what the data says.
month_cache.CHECK = True


@pytest.fixture(autouse=True)
def _household_left_as_found(request):
    """A browser test on the shared household takes away the accounts it made, with what is
    in them: the household is shared by every test on a worker, in whatever order they come,
    and a test's leftovers changed another's figures (a 529 in an empty tax year, a coin
    account's 1099-DA among the expected documents). What a module's fixture made, before the
    test, stays."""
    if "household" not in request.fixturenames:
        yield
        return
    from browser import Household
    from edits import remove

    h = request.getfixturevalue("household")
    if not isinstance(h, Household):  # a module's own household, not the browser tests' one
        yield
        return

    def ids() -> set[str]:
        return {a["id"] for a in h.c.get("/ui/api/accounts").json()["items"]}

    before = ids()
    yield
    for gone in ids() - before:
        record = h.c.get(f"/ui/api/accounts/{gone}").json()
        r = remove(h.c, "Acct", record, confirm=True)
        assert r.status_code == 200, f"a test's account left in the household: {r.text}"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """A test failing on a server's 5xx (a page's problems, a wait) carries the servers' logs,
    so a bug reached only in CI shows its traceback in the run that hit it (issue #34)."""
    outcome = yield
    rep = outcome.get_result()
    # "500 for <url>" from a page's problems, ": 500 {…}" from an API helper's assertion.
    if rep.failed and rep.when == "call" and re.search(r"\b5\d\d (for |\{)", str(rep.longrepr)):
        from browser import server_log_tail

        paths = sorted(
            set(re.findall(r"\b5\d\d for \w+://[^/\s]+(/[^\s'\"?]*)", str(rep.longrepr)))
        )
        rep.sections.append(("the servers' logs, their tracebacks", server_log_tail(paths=paths)))


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    """MK_TEST_PART=k/n keeps the k-th of n parts, once the marks have chosen the tests, split
    by measured time (`parts.py`): CI runs the server's tests and the browser tests in parts
    side by side (S17.10.1). Tests of one xdist_group, which run one after another, stay in
    one part."""
    part = os.environ.get("MK_TEST_PART")
    if not part:
        return
    k, n = (int(x) for x in part.split("/"))
    assert 1 <= k <= n, f"MK_TEST_PART={part}"
    named = []
    for item in items:
        group = item.get_closest_marker("xdist_group")
        named.append((item.nodeid, group.args[0] if group else None))
    keep = parts.choose(named, k, n, *parts.load())
    left = [item for item, ok in zip(items, keep, strict=True) if not ok]
    config.hook.pytest_deselected(items=left)
    items[:] = [item for item, ok in zip(items, keep, strict=True) if ok]


_took = parts.Recorder()


def pytest_runtest_logreport(report):
    """What each test took, for MK_DURATIONS (`parts.py`)."""
    if os.environ.get("MK_DURATIONS"):
        _took.add(report.nodeid, report.duration)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session):
    """The run's times written where MK_DURATIONS says, by the process that ran or gathered
    every test. An xdist worker measured by coverage (S17.5.8) saves what it measured once its
    fixtures are torn down and before it reports finished: once every worker has, xdist gives
    each 10 s to exit and then kills it, and a worker killed while saving at exit loses its
    tests' coverage."""
    if not hasattr(session.config, "workerinput"):
        if out := os.environ.get("MK_DURATIONS"):
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_text(json.dumps(_took.written(), indent=1) + "\n")
        return
    import coverage

    if cov := coverage.Coverage.current():
        cov.stop()
        cov.save()


def pytest_terminal_summary(terminalreporter):
    """Each generated world's time, added up over its tests (setup, call and teardown), so a
    world that grows shows in CI's log (S17.5.8)."""
    by: dict[str, float] = {}
    for reports in terminalreporter.stats.values():
        for r in reports:
            nodeid = getattr(r, "nodeid", "")
            module = nodeid.split("::")[0].rsplit("/", 1)[-1]
            if module.startswith("test_") and "world" in module:
                by[module] = by.get(module, 0.0) + getattr(r, "duration", 0.0)
    if by:
        terminalreporter.write_sep("-", "generated worlds")
        for module, secs in sorted(by.items(), key=lambda kv: -kv[1]):
            terminalreporter.write_line(f"{secs:8.1f} s  {module}")


@pytest.fixture(autouse=True)
def file_sandbox_shown():
    """What a test sees doesn't depend on the kernel it runs on: the reader's file sandbox is
    shown as there (S9.8.4.2), unless the test pins it otherwise."""
    from moolakata import parsing

    parsing.PINNED = True
    yield
    parsing.PINNED = None


@pytest.fixture
def config(tmp_path) -> Config:
    return Config(
        name="test",
        mode="proxy",
        data_dir=tmp_path / "data",
        backup_dir=tmp_path / "backups",
        socket_path=tmp_path / "run" / "sock",
    )


@pytest.fixture(scope="session")
def migrated(tmp_path_factory) -> tuple[Path, bytes]:
    """A keyring and a database brought to head, made once per worker: each test's keyring and
    store start from copies of them, so the migrations run once per worker rather than once
    per test (they were most of a test's setup). open_store still opens each copy as the
    server does; the migration tests build their databases from nothing."""
    at = tmp_path_factory.mktemp("migrated")
    config = Config(name="test", mode="proxy", data_dir=at / "data", backup_dir=at / "backups",
                    socket_path=at / "run" / "sock")  # fmt: skip
    key = os.urandom(16)
    master.create_keyring(config, key)
    open_store(config, key).db.dispose()
    return config.data_dir, key


@pytest.fixture
def master_key(migrated) -> bytes:
    """The recovery phrase's key, which a test holds as the admin holds the phrase: it is
    never on disk (S15.4). The worker's own, which wraps the keyring each test copies."""
    return migrated[1]


@pytest.fixture
def bare_client(config):
    """The app with no database: static files, headers and middleware only."""
    server = Server(config=config, ready=True)
    with TestClient(create_app(server), base_url="http://mk.test", client=LOOPBACK) as c:
        yield c


@pytest.fixture
def keyed_config(config, migrated) -> Config:
    """A config whose keyring exists, wrapped under `master_key` (made without the phrase's
    three-word confirmation): the worker's keyring, copied."""
    config.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    shutil.copy2(migrated[0] / config.keyring_path.name, config.keyring_path)
    return config


@pytest.fixture
def store(keyed_config, master_key, migrated):
    """The store, opened on a copy of the worker's database at head."""
    shutil.copy2(migrated[0] / keyed_config.db_path.name, keyed_config.db_path)
    st = open_store(keyed_config, master_key)
    yield st
    st.db.dispose()


@pytest.fixture
def db(store):
    return store.db


passwords.use_fast_hashing_for_tests()
ORIGIN = "https://mk.test"
ADMIN_PW = "a long admin passphrase"
# Where a test client calls from: an address, as a real client has (Settings › Network, S16.14).
LOOPBACK = ("127.0.0.1", 50000)


@pytest.fixture
def server(store, keyed_config):
    from moolakata.store.repos.ledger import ensure_categories

    srv = Server(config=keyed_config, store=store, ready=True)
    with srv.db.tx(unscoped="test") as s:
        # The first admin, as the welcome makes it (S10.1.2).
        accounts.make_first_admin(s, "Ada Admin", "male", "admin@home.lan", ADMIN_PW)
        ensure_categories(s)
    return srv


class Exact(Decimal):
    """A number with a decimal point as a test reads it: a Decimal that also equals the exact
    text the server wrote, so `== "1234.50"` checks the digits and `== 7.5` the value."""

    def __new__(cls, text):
        d = super().__new__(cls, text)
        d.text = text
        return d

    def __eq__(self, other):
        if isinstance(other, str):
            return self.text == other
        if isinstance(other, float):  # a test's float literal, by its shortest digits
            return super().__eq__(Decimal(repr(other)))
        return super().__eq__(other)

    __hash__ = Decimal.__hash__

    def __repr__(self):
        return f"Exact({self.text})"


class ExactClient(TestClient):
    """The API's exact numbers (S13.8.2) as tests read them: `response.json()` gives a number
    with a decimal point as an `Exact`. A request's json may hold Decimals, sent as exact number
    literals."""

    def request(self, method, url, *args, **kw):
        if kw.get("json") is not None:
            kw["content"] = exactjson.dumps(kw.pop("json")).encode()
            kw["headers"] = {**(kw.get("headers") or {}), "Content-Type": "application/json"}
        headers = {k.lower() for k in (kw.get("headers") or {})}
        if method.upper() in ("PATCH", "PUT", "DELETE") and "if-match" not in headers:
            # A test that isn't about versions (S13.8.6) makes its change against whatever
            # version the record has: 0 first, which creates what doesn't exist yet, and if
            # that is stale, the version the 412 names. A test about versions sends its own.
            kw["headers"] = {**(kw.get("headers") or {}), "If-Match": '"0"'}
            r = self._send(method, url, *args, **kw)
            if r.status_code == 412 and "version" in (r.json() or {}):
                kw["headers"]["If-Match"] = f'"{r.json()["version"]}"'
                r = self._send(method, url, *args, **kw)
            return r
        return self._send(method, url, *args, **kw)

    def _send(self, method, url, *args, **kw):
        r = super().request(method, url, *args, **kw)
        r.json = lambda **_: json.loads(r.content, parse_float=Exact) if r.content else None
        return r


def new_client(srv) -> TestClient:
    return ExactClient(
        create_app(srv), base_url=ORIGIN, headers={"Origin": ORIGIN}, client=LOOPBACK
    )


@pytest.fixture
def client(server):
    with new_client(server) as c:
        yield c


@pytest.fixture
def admin_client(server):
    """Signed in as the first admin."""
    with new_client(server) as c:
        r = c.post("/ui/api/session", json={"login": "admin", "password": ADMIN_PW})
        assert r.status_code == 200, r.text
        yield c


def make_user(
    srv,
    username: str,
    password: str = "a long user passphrase",
    admin: bool = False,
    email: str | None = None,
    sex: str = "female",
    born: int | None = None,
):
    """A user who has joined, made straight in the database, with their person."""
    from moolakata import ids, people
    from moolakata.store.entities.users import User, UserGroup

    with srv.db.tx(unscoped="test") as s:
        u = User(
            id=ids.new_id("User"),
            personId=people.make(s, username.title(), sex, birth_year=born).id,
            username=username,
            displayName=username.title(),
            email=email or f"{username}@home.lan",
            passwordHash=passwords.hash_password(password),
        )
        s.add(u)
        s.flush()
        if admin:
            s.add(
                UserGroup(
                    userId=u.id, groupId=accounts.admins_group(s).id, createdAt=accounts.now()
                )
            )
        return u


def sign_in(srv, username: str, password: str = "a long user passphrase") -> TestClient:
    c = new_client(srv)
    c.__enter__()
    r = c.post("/ui/api/session", json={"login": username, "password": password})
    assert r.status_code == 200, r.text
    return c


def stale(srv) -> None:
    """Every session's password last given 11 minutes ago, past re-authentication's 10."""
    import datetime as dt

    from sqlalchemy import select

    from moolakata.store.entities.users import Session

    with srv.db.tx(unscoped="test") as s:
        for row in s.scalars(select(Session)):
            row.authAt -= dt.timedelta(minutes=11)
