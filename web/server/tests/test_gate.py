"""The gate every signed call passes (links/gate.py; requirements S13.7.5.4, S13.7.6;
link-protocol.md §3, connector-protocol.md §3), on its axes: each way a call can fail its checks
× each protocol × each kind of body. A refused call is refused before a byte of its body is
read and leaves no trace: nothing counted against the key it names, no upload held, no file
written, no row added. A body that takes longer than the clocks allow is still taken: its time
is checked when it arrives. Then every signed route of both routers: each goes through the
gate, and a forged call naming a real key leaves no trace on any of them."""

import itertools
import time

import pytest
from conftest import new_client
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from starlette.requests import Request
from starlette.routing import Route
from test_connector import FakeConnector, admin, pair_code, paired  # noqa: F401

from moolakata import exactjson, ids, middleware
from moolakata.connector import routes as connector_routes
from moolakata.links import keys, signing
from moolakata.links import routes as link_routes
from moolakata.store.entities.links import Link
from moolakata.store.tables._base import metadata

ATTACKS = ("unsigned", "bad-signature", "unknown-key", "replayed", "stale", "too-large", "mismatch")
KINDS = (("link", "json"), ("link", "file"), ("connector", "json"), ("connector", "multipart"))
EXPECTED = {
    "unsigned": "unsigned",
    "bad-signature": "bad-signature",
    "replayed": "replayed",
    "stale": "clock-skew",
    "too-large": "too-large",
    "mismatch": "bad-signature",
}


class Side:
    """One protocol's caller, as the server knows it: a key it trusts, the paths a body kind
    goes to, and how its calls are counted."""

    def __init__(self, protocol, srv, client, key, counted):
        self.protocol, self.srv, self.client, self.key, self.counted = (
            protocol,
            srv,
            client,
            key,
            counted,
        )
        self.scheme = signing.LINK if protocol == "link" else signing.CONN
        self.kind = link_routes.KIND if protocol == "link" else connector_routes.KIND
        self.fp = keys.own_public(srv)[1]

    def path(self, body_kind: str) -> str:
        return {
            ("link", "json"): "/link/v1/ping",
            ("link", "file"): "/link/v1/deliver",
            ("connector", "json"): "/connector/v1/report",
            ("connector", "multipart"): "/connector/v1/accounts/Acct_x/files",
        }[(self.protocol, body_kind)]

    def content_type(self, body_kind: str) -> str:
        return {
            "json": "application/json",
            "file": "application/octet-stream",
            "multipart": "multipart/form-data; boundary=b",
        }[body_kind]

    def body(self, body_kind: str) -> bytes:
        if body_kind == "json":
            return b"{}"
        if body_kind == "file":
            return b"s" * 200_000  # sealed bytes, as a receipt crosses
        return b'--b\r\nContent-Disposition: form-data; name="meta"\r\n\r\n{}\r\n--b--\r\n'

    def headers(self, path, body, key=None, named=None, now=None, digest=None, body_kind="json"):
        key = key or self.key
        signed = signing.sign_request(key, "POST", path, body, self.fp, now=now, scheme=self.scheme)
        h = {
            **signed.headers,
            self.scheme.h("Body-SHA256"): digest or signed.body_hash,
            self.scheme.h("Protocol"): "1",
            "Content-Type": self.content_type(body_kind),
        }
        if body_kind == "file":
            h["MK-Link-File"] = "Rcpt_" + "0" * 26
        if named is not None:
            h[self.scheme.h("Key")] = keys.b64(keys.raw_public(named.public_key()))
        return h

    def limit_count(self) -> int:
        return self.kind.limit(self.srv).count(self.counted)


@pytest.fixture
def link_side(server):
    key = Ed25519PrivateKey.generate()
    with server.db.tx(unscoped="test") as s:
        row = Link(
            id=ids.new_id("Link"),
            state="active",
            role="inviter",
            address="https://peer.test",
            peerKey=keys.b64(keys.raw_public(key.public_key())),
        )
        s.add(row)
        link_id = row.id
    with new_client(server) as c:
        yield Side("link", server, c, key, link_id)


@pytest.fixture
def connector_side(server, paired, client):  # noqa: F811
    return Side(
        "connector", server, client, paired.key, keys.b64(keys.raw_public(paired.key.public_key()))
    )


@pytest.fixture
def side(request):
    return request.getfixturevalue(f"{request.param}_side")


@pytest.fixture
def reads(monkeypatch):
    """The paths whose body was read, by any route or the gate."""
    seen: list[str] = []
    stream, body = Request.stream, Request.body

    async def streamed(self):
        seen.append(self.url.path)
        async for chunk in stream(self):
            yield chunk

    async def bodied(self):
        seen.append(self.url.path)
        return await body(self)

    monkeypatch.setattr(Request, "stream", streamed)
    monkeypatch.setattr(Request, "body", bodied)
    return seen


def body_limit(client) -> middleware.BodyLimit:
    layer = client.app.middleware_stack
    while layer is not None and not isinstance(layer, middleware.BodyLimit):
        layer = getattr(layer, "app", None)
    assert layer is not None
    return layer


def trace(side: Side) -> dict:
    """What a call can leave behind: its count against the key, uploads held, files under the
    data folder (the databases' own files aside), and every table's rows."""
    files = sorted(
        str(p.relative_to(side.srv.config.data_dir))
        for p in side.srv.config.data_dir.rglob("*")
        if p.is_file() and ".db" not in p.name and "keyring" not in str(p)
    )
    with side.srv.db.read(unscoped="test") as s:
        rows = {
            t.name: s.execute(t.select().with_only_columns(t.c[0])).all().__len__()
            for t in metadata.sorted_tables
        }
    side.client.get("/healthz")  # the middleware is built at the first call
    return {
        "limit": side.limit_count(),
        "in flight": dict(body_limit(side.client).in_flight),
        "files": files,
        "rows": rows,
    }


def attack(side: Side, kind: str, how: str):
    path, body = side.path(kind), side.body(kind)
    stranger = Ed25519PrivateKey.generate()
    if how == "unsigned":
        h = {
            side.scheme.h("Key"): keys.b64(keys.raw_public(side.key.public_key())),
            "Content-Type": side.content_type(kind),
        }
        return side.client.post(path, content=body, headers=h)
    if how == "bad-signature":
        h = side.headers(path, body, key=stranger, named=side.key, body_kind=kind)
        return side.client.post(path, content=body, headers=h)
    if how == "unknown-key":
        return side.client.post(
            path, content=body, headers=side.headers(path, body, key=stranger, body_kind=kind)
        )
    if how == "stale":
        h = side.headers(path, body, now=time.time() - 61, body_kind=kind)
        return side.client.post(path, content=body, headers=h)
    if how == "too-large":
        h = side.headers(path, body, body_kind=kind)
        h["Content-Length"] = str(10 * 1024**3)  # says more than any path takes
        return side.client.post(path, content=body, headers=h)
    if how == "mismatch":
        h = side.headers(path, body, body_kind=kind)
        return side.client.post(path, content=body[:-1] + b"!", headers=h)
    raise AssertionError(how)


@pytest.mark.parametrize(
    ("side", "kind", "how"),
    [(p, k, a) for (p, k), a in itertools.product(KINDS, ATTACKS)],
    indirect=["side"],
)
def test_a_call_that_fails_the_gate_leaves_no_trace(side, kind, how, reads):
    before = trace(side)
    if how == "replayed":
        path, body = side.path(kind), side.body(kind)
        h = side.headers(path, body, body_kind=kind)
        side.client.post(path, content=body, headers=h)  # the call itself, taken
        before, reads[:] = trace(side), []
        r = side.client.post(path, content=body, headers=h)
    else:
        r = attack(side, kind, how)
    after = trace(side)
    code = r.json()["code"]
    if how == "unknown-key":
        assert code == ("not-linked" if side.protocol == "link" else "not-paired")
    else:
        assert code == EXPECTED[how], r.text
    assert r.status_code in (403, 413), r.text
    if how == "mismatch":
        # Signed by the real key over another body: counted against it, read, and refused.
        assert after["limit"] == before["limit"] + 1
        assert reads, "read, since its signature checked"
        after["limit"] = before["limit"]
    else:
        assert reads == [], "refused before a byte of the body was read"
    assert after == before, "no trace"
    signed = side.scheme.lower("signature") in {k.lower() for k in r.headers}
    if how in ("unsigned", "too-large"):
        assert not signed, "refused before it was a call: unsigned"
    else:
        assert signed, "a refusal is signed to the call, so it can be told from a forgery"


@pytest.mark.parametrize(("side", "kind"), KINDS, indirect=["side"])
def test_a_body_that_takes_longer_than_the_clocks_allow_is_taken(side, kind, monkeypatch):
    """CR3-53: the call's time is checked when its headers arrive; its body may then take as
    long as the line needs. Here each piece of it moves the server's clock 30 seconds."""
    if (side.protocol, kind) not in KINDS:
        pytest.skip("not a body this protocol sends")
    path, body = side.path(kind), side.body(kind)
    if kind == "json":
        body = b'{"note":"' + b"x" * 600 + b'"}'  # enough to come in three pieces
    h = side.headers(path, body, body_kind=kind)
    offset = [0.0]
    real = time.time

    class Clock:
        @staticmethod
        def time():
            return real() + offset[0]

    monkeypatch.setattr(signing, "time", Clock)

    def pieces():
        third = -(-len(body) // 3)
        for i in range(0, len(body), third):
            offset[0] += 30
            yield body[i : i + third]

    r = side.client.post(path, content=pieces(), headers=h)
    assert offset[0] >= 90
    assert r.json().get("code") not in ("clock-skew", "bad-signature", "unsigned"), r.text


def signed_routes():
    for router in (link_routes.router, connector_routes.router):
        for route in router.routes:
            if isinstance(route, Route) and route.methods & {"POST"}:
                yield route


def test_every_signed_route_goes_through_the_gate():
    """A route written without the gate would read its body before its signature."""
    named = [r.path for r in signed_routes()]
    assert len(named) == 14, named
    for route in signed_routes():
        assert getattr(route.endpoint, "gate", None) is not None, route.path
    for router in (link_routes.router, connector_routes.router):
        for route in router.routes:
            if isinstance(route, Route) and route.methods == {"GET"}:
                assert route.path.endswith("/hello"), "only the hello is unsigned"


@pytest.mark.parametrize("protocol", ["link", "connector"])
def test_a_forged_call_naming_a_real_key_leaves_no_trace_on_any_route(protocol, request, reads):
    side = request.getfixturevalue(f"{protocol}_side")
    reads.clear()  # the pairing and the admin's sign-in, setting up
    prefix = "/link/" if protocol == "link" else "/connector/"
    stranger = Ed25519PrivateKey.generate()
    for route in signed_routes():
        if not route.path.startswith(prefix):
            continue
        path = route.path.replace("{connection_id}", "Conn_x").replace("{account_id}", "Acct_x")
        body = exactjson.dumps({}).encode()
        before = trace(side)
        h = side.headers(path, body, key=stranger, named=side.key)
        r = side.client.post(path, content=body, headers=h)
        assert r.json()["code"] == "bad-signature", (path, r.text)
        assert reads == [], path
        after = trace(side)
        assert after == before, (
            path,
            {k: (before[k], after[k]) for k in before if before[k] != after[k]},
        )


@pytest.mark.parametrize("protocol", ["link", "connector"])
def test_a_routes_work_never_holds_the_event_loop(protocol, request, monkeypatch):
    """CR3-51, S13: while one call's work runs (here held until the test lets it go), the
    server answers others. Two calls in flight at once, in the process; the test waits on
    events, never on a clock."""
    import asyncio
    import threading

    import httpx
    from conftest import LOOPBACK, ORIGIN

    from moolakata.connector import manage as connector_manage
    from moolakata.links import manage as link_manage

    side = request.getfixturevalue(f"{protocol}_side")
    started, release = threading.Event(), threading.Event()

    def held(*args, **kw):
        started.set()
        assert release.wait(30), "let go by the test"
        return {}

    if protocol == "link":
        monkeypatch.setattr(link_manage, "answer_exchange", held)
        path = "/link/v1/exchange"
    else:
        monkeypatch.setattr(connector_manage, "apply_report", held)
        path = "/connector/v1/report"
    body = b"{}"
    h = side.headers(path, body)

    async def both():
        transport = httpx.ASGITransport(app=side.client.app, client=LOOPBACK)
        async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as c:
            call = asyncio.create_task(c.post(path, content=body, headers=h))
            assert await asyncio.to_thread(started.wait, 30), "the call's work began"
            health = await asyncio.wait_for(c.get("/healthz"), 30)
            release.set()
            return health, await asyncio.wait_for(call, 30)

    health, answered = asyncio.run(both())
    assert health.status_code == 200, "answered while the other call's work ran"
    assert answered.status_code == 200, answered.text
