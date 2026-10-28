"""Two MoolaKata servers in one test, their link calls wired to each other's app."""

import dataclasses
from urllib.parse import urlsplit

import httpx
from fastapi.testclient import TestClient

from moolakata import net
from moolakata.app import Server, create_app
from moolakata.config import Config
from moolakata.keys import cli as keys_cli
from moolakata.links import client as link_client
from moolakata.store.maintenance import open_store
from moolakata.store.repos.ledger import ensure_categories


def make_server(tmp_path, name: str) -> Server:
    cfg = Config(
        name=name,
        mode="proxy",
        data_dir=tmp_path / name / "data",
        backup_dir=tmp_path / name / "backups",
    )
    key = keys_cli.init(cfg, say=lambda _: None, confirm=False)
    srv = Server(config=cfg, store=open_store(cfg, key), ready=True)
    # The test names resolve to an address on a LAN, as a peer's does (S13.5).
    srv.guard = net.Guard(resolver=lambda host, port: ["192.0.2.10"])
    with srv.db.tx() as s:
        ensure_categories(s)
    return srv


class Wire:
    """Routes https://<name>.test/... to that server's app, as the network would, with the
    real transport's ceiling on an answer (`net.Client`'s `max_bytes`), so a test meets the
    limits a link meets (S13.5). `fail` breaks one call at a time: given the method and the
    URL, it gives an exception to raise in place of the call, or None."""

    def __init__(self):
        self.apps: dict[str, TestClient] = {}
        self.down: set[str] = set()
        self.fail = None

    def add(self, name: str, srv: Server) -> str:
        self.apps[f"{name}.test"] = TestClient(
            create_app(srv), base_url=f"https://{name}.test", client=("127.0.0.1", 50000)
        )
        return f"https://{name}.test"

    def client(self, guard=None, max_bytes: int = net.MAX_RESPONSE, **kw):
        wire = self

        def reach(method, url, kw):
            host = urlsplit(url).hostname
            if guard is not None:
                guard.check(host, 443)  # as the real transport does
            if host in wire.down or host not in wire.apps:
                raise httpx.ConnectError("unreachable")
            broken = wire.fail(method, url, kw) if wire.fail else None
            if broken is not None:
                raise broken
            return wire.apps[host]

        def capped(r, url):
            if len(r.content) > max_bytes:
                raise net.ResponseTooLarge(f"the response from {url} is larger than allowed")
            return r

        class Capped:
            """A streamed answer read only up to the ceiling, as `net._Capped` reads it."""

            def __init__(self, inner):
                self._inner = inner

            def __enter__(self):
                r = self._inner.__enter__()
                raw = r.iter_bytes

                def iter_bytes(*a, **k):
                    size = 0
                    for chunk in raw(*a, **k):
                        size += len(chunk)
                        if size > max_bytes:
                            raise net.ResponseTooLarge("the response is larger than allowed")
                        yield chunk

                r.iter_bytes = iter_bytes
                return r

            def __exit__(self, *exc):
                return self._inner.__exit__(*exc)

        class C:
            def _go(self, method, url, **kw):
                return capped(reach(method, url, kw).request(method, url, **kw), url)

            def get(self, url, **kw):
                return self._go("GET", url, **kw)

            def post(self, url, **kw):
                return self._go("POST", url, **kw)

            def stream(self, method, url, **kw):
                return Capped(reach(method, url, kw).stream(method, url, **kw))

        return C()

    def install(self, monkeypatch):
        monkeypatch.setattr(link_client.net, "Client", self.client)

    def close(self):
        for c in self.apps.values():
            c.close()


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
