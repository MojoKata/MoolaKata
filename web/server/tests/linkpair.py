"""Two MoolaKata servers in one test, their link calls wired to each other's app."""

import dataclasses
import hashlib
import os
from urllib.parse import urlsplit

import httpx
from fastapi.testclient import TestClient

from moolakata import net
from moolakata.app import Server, create_app
from moolakata.config import Config
from moolakata.keys import master
from moolakata.store.maintenance import open_store
from moolakata.store.repos.ledger import ensure_categories


def make_server(tmp_path, name: str) -> Server:
    cfg = Config(
        name=name,
        mode="proxy",
        data_dir=tmp_path / name / "data",
        backup_dir=tmp_path / name / "backups",
    )
    key = os.urandom(16)
    master.create_keyring(cfg, key)
    srv = Server(config=cfg, store=open_store(cfg, key), ready=True)
    # The test names resolve to an address on a LAN, as a peer's does (S13.5).
    srv.guard = net.Guard(resolver=lambda host, port: ["192.0.2.10"])
    with srv.db.tx() as s:
        ensure_categories(s)
    return srv


class Wire:
    """Routes https://<name>.test/... to that server's app, as the network would. It stands
    where the sockets are (`net.network`), so everything `net.Client` does above them, the
    guard's check, the decoding and the ceiling on an answer (S13.5), is the real code, and a
    test meets the limits a link meets. Each server presents a certificate key of its own
    (`certs`), held to a pinned call's pins as TLS holds it. `fail` breaks one call at a time:
    given the method, the URL and the request, it gives an exception to raise in place of the
    call, or None. `watch`, given the request and the answer's body, sees what crosses."""

    def __init__(self):
        self.apps: dict[str, TestClient] = {}
        self.certs: dict[str, str] = {}
        self.down: set[str] = set()
        self.fail = None
        self.watch = None

    def add(self, name: str, srv: Server) -> str:
        host = f"{name}.test"
        self.apps[host] = TestClient(
            create_app(srv), base_url=f"https://{host}", client=("127.0.0.1", 50000)
        )
        self.certs[host] = hashlib.sha256(host.encode()).hexdigest()
        return f"https://{host}"

    def network(self, guard: net.Guard, pins: frozenset[str] | None) -> httpx.BaseTransport:
        return _Network(self, guard, pins)

    def install(self, monkeypatch):
        monkeypatch.setattr(net, "network", self.network)

    def close(self):
        for c in self.apps.values():
            c.close()


class _Presented:
    """The connection an answer came over, as `net.presented` reads it."""

    def __init__(self, key: str | None):
        self._key = key

    def get_extra_info(self, info: str):
        return self._key if info == net.PRESENTED else None


class _Network(httpx.BaseTransport):
    def __init__(self, wire: Wire, guard: net.Guard, pins: frozenset[str] | None):
        self._wire, self._guard, self._pins = wire, guard, pins

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        wire, host = self._wire, request.url.host
        self._guard.check(host, request.url.port or 443)  # as the sockets' backend does
        if host in wire.down or host not in wire.apps:
            raise httpx.ConnectError("unreachable")
        broken = wire.fail(request.method, str(request.url), request) if wire.fail else None
        if broken is not None:
            raise broken
        cert = wire.certs[host]
        if self._pins is not None and cert not in self._pins:
            raise net.CertificateRefused(cert)
        got = wire.apps[host]._transport.handle_request(request)
        body = got.read()
        if wire.watch is not None:
            wire.watch(request, body)
        # Its body as the sockets give one, unread, so `net` reads it as it reads theirs.
        pieces = [body[i : i + 65536] for i in range(0, len(body), 65536)]
        return httpx.Response(
            got.status_code,
            headers=got.headers,
            content=iter(pieces),
            extensions={"network_stream": _Presented(cert if self._pins is not None else None)},
        )


def with_config(srv: Server, **kw) -> None:
    srv.config = dataclasses.replace(srv.config, **kw)


def admin_of(srv: Server, base: str) -> TestClient:
    """An admin signed in on that server's own UI: the first one, made as the welcome makes it
    (S10.1.2), and signed in again when it exists."""
    from moolakata import settings

    with srv.db.tx() as s:
        settings.put(s, "publicUrl", base, None)
    c = TestClient(
        create_app(srv), base_url=base, headers={"Origin": base}, client=("127.0.0.1", 50000)
    )
    host = urlsplit(base).hostname
    r = c.post(
        "/ui/api/welcome/admin",
        json={
            "password": "a long admin passphrase",
            "email": f"admin@{host}",
            "displayName": f"Admin {host[0].upper()}",
            "sex": "male",
        },
    )
    if r.status_code == 409:
        login = {"login": "admin", "password": "a long admin passphrase"}
        r = c.post("/ui/api/session", json=login)
    assert r.status_code == 200, r.text
    return c


def linked(a_admin: TestClient, b_admin: TestClient) -> tuple[str, str]:
    """A link made the way admins make it: invited on A, joined on B, approved on A."""
    code = a_admin.post("/ui/api/settings/links/invitations").json()["code"]
    b_link = b_admin.post("/ui/api/settings/links/join", json={"code": code})
    assert b_link.status_code == 201, b_link.text
    a_link = next(
        x
        for x in a_admin.get("/ui/api/settings/links").json()["links"]
        if x["state"] == "requested"
    )
    r = a_admin.post(f"/ui/api/settings/links/{a_link['id']}/approve")
    assert r.status_code == 200, r.text
    return a_link["id"], b_link.json()["id"]
