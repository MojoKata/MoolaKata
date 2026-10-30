import json
import os
from decimal import Decimal

import pytest

# The browser tests' shared fixtures (S17.5.2), defined once for every module that uses them.
from browser import browser, household, served  # noqa: F401
from fastapi.testclient import TestClient
from jscoverage import install as measure_the_browser_app

from moolakata import exactjson
from moolakata.app import Server, create_app
from moolakata.auth import passwords
from moolakata.auth import users as accounts
from moolakata.config import Config
from moolakata.keys import master
from moolakata.store.maintenance import open_store

measure_the_browser_app()


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


@pytest.fixture
def master_key() -> bytes:
    """The recovery phrase's key, which a test holds as the admin holds the phrase: it is
    never on disk (S15.4)."""
    return os.urandom(16)


@pytest.fixture
def bare_client(config):
    """The app with no database: static files, headers and middleware only."""
    server = Server(config=config, ready=True)
    with TestClient(create_app(server), base_url="http://mk.test", client=LOOPBACK) as c:
        yield c


@pytest.fixture
def keyed_config(config, master_key) -> Config:
    """A config whose keyring exists, wrapped under `master_key` (made without the phrase's
    three-word confirmation)."""
    master.create_keyring(config, master_key)
    return config


@pytest.fixture
def store(keyed_config, master_key):
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
    with srv.db.tx() as s:
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

    with srv.db.tx() as s:
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

    with srv.db.tx() as s:
        for row in s.scalars(select(Session)):
            row.authAt -= dt.timedelta(minutes=11)
