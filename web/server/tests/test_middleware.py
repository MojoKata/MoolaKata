from fastapi.testclient import TestClient

from moolakata.app import Server, create_app
from moolakata.config import Config


def test_every_response_carries_the_security_headers(bare_client):
    for path in ("/ui/", "/ui/api/none", "/healthz", "/demo"):
        h = bare_client.get(path).headers
        assert h["x-content-type-options"] == "nosniff"
        assert h["referrer-policy"] == "no-referrer"
        assert h["cross-origin-opener-policy"] == "same-origin"
        assert h["cross-origin-resource-policy"] == "same-origin"
        assert "camera=()" in h["permissions-policy"]
        assert "frame-ancestors 'none'" in h["content-security-policy"]
        assert "strict-transport-security" not in h


def test_tls_mode_adds_hsts(config):
    server = Server(config=Config(**{**config.__dict__, "mode": "tls"}), ready=True)
    with TestClient(create_app(server)) as c:
        assert c.get("/healthz").headers["strict-transport-security"] == "max-age=31536000"


def test_changes_need_the_apps_own_origin(bare_client):
    for headers in ({}, {"Origin": "https://evil.example"}, {"Origin": "http://mk.test.evil"}):
        r = bare_client.post("/ui/api/anything", json={}, headers=headers)
        assert r.status_code == 403, headers
        assert r.json()["code"] == "origin-refused"
    r = bare_client.post("/ui/api/anything", json={}, headers={"Origin": "http://mk.test"})
    assert r.status_code == 404


def test_json_bodies_are_limited_to_1_mb(bare_client):
    big = b"[" + b"0," * 600_000 + b"0]"
    r = bare_client.post(
        "/ui/api/anything",
        content=big,
        headers={"Origin": "http://mk.test", "Content-Type": "application/json"},
    )
    assert r.status_code == 413


def test_healthz_says_starting_until_ready(config):
    server = Server(config=config)
    with TestClient(create_app(server)) as c:
        assert c.get("/healthz").status_code == 503
        server.ready = True
        assert c.get("/healthz").json()["status"] == "ok"


def test_forwarded_headers_only_from_trusted_proxies(config):
    import ipaddress

    from moolakata.middleware import ClientAddress

    seen = {}

    async def app(scope, receive, send):
        seen.update(client=scope["client"][0], scheme=scope["scheme"])

    import asyncio

    def call(peer, headers, trusted):
        mw = ClientAddress(app, "proxy", tuple(ipaddress.ip_network(t) for t in trusted))
        scope = {
            "type": "http",
            "client": (peer, 1),
            "scheme": "http",
            "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
        }
        asyncio.run(mw(scope, None, None))
        return dict(seen)

    fwd = {"x-forwarded-for": "203.0.113.9, 10.0.0.2", "x-forwarded-proto": "https"}
    assert call("10.0.0.1", fwd, ["10.0.0.0/8"]) == {"client": "203.0.113.9", "scheme": "https"}
    assert call("192.0.2.1", fwd, ["10.0.0.0/8"]) == {"client": "192.0.2.1", "scheme": "http"}


def test_an_outbound_client_always_verifies_tls():
    """TLS is never turned off (S11.1.3, S13.5): a server's own certificate is pinned instead."""
    import ssl

    import pytest

    from moolakata import net

    with pytest.raises(TypeError):
        net.Client(net.Guard(), verify=False)
    assert (
        net.Client(net.Guard())._transport._inner._pool._ssl_context.verify_mode
        == ssl.CERT_REQUIRED
    )
    pinned = net.Client(net.Guard(), pins=["ab" * 32])._transport._inner._pool._ssl_context
    assert pinned.verify_mode == ssl.CERT_NONE, "the key decides, checked after the handshake"


def test_uploads_in_flight_are_capped_per_caller(server, monkeypatch):
    # N9: at most 100 MB arriving at once for one caller (S13.7.6), here a smaller cap.
    from conftest import make_user, sign_in

    from moolakata import middleware

    make_user(server, "alice")
    c = sign_in(server, "alice")
    monkeypatch.setattr(middleware, "IN_FLIGHT", 1000)
    r = c.post("/ui/api/receipts", files={"file": ("big.png", b"x" * 5000)})
    assert r.status_code == 429 and r.json()["code"] == "uploads-in-flight", r.text
    r = c.post("/ui/api/receipts", files={"file": ("small.png", b"x" * 100)})
    assert r.status_code != 429, "the count is let go when a request ends"


def test_an_ipv6_address_counts_by_its_64():
    from moolakata.ratelimit import address_key

    assert address_key("2001:db8:1:2::5") == address_key("2001:db8:1:2:ffff::1")
    assert address_key("2001:db8:1:2::5") != address_key("2001:db8:1:3::5")
    assert address_key("::ffff:192.0.2.7") == "192.0.2.7" == address_key("192.0.2.7")


def test_every_problem_is_logged_by_its_id_status_and_code(bare_client, caplog):
    # S13.7.8: a refusal's id is in the log with its status and code, never its detail.
    with caplog.at_level("INFO", logger="moolakata.errors"):
        r = bare_client.get("/ui/api/no-such-thing")
    assert r.status_code == 404
    line = f"problem {r.json()['errorId']} 404 not-found"
    assert any(rec.getMessage() == line for rec in caplog.records), caplog.text


def test_the_connectors_uploads_count_as_read_and_everyones_have_a_ceiling(monkeypatch):
    """CR3-71 (S13.7.6): a call to /connector reserves nothing for what it says it carries, so a
    stranger's key header holds no budget (its route reads a body only once the paired
    connector's signature checks out); and all callers together have a ceiling."""
    import asyncio

    from moolakata import middleware

    monkeypatch.setattr(middleware, "IN_FLIGHT", 1000)
    monkeypatch.setattr(middleware, "IN_FLIGHT_ALL", 1500)
    answered = []

    async def app(scope, receive, send):  # an app that never reads the body
        await send({"type": "http.response.start", "status": 403, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    mw = middleware.BodyLimit(
        app, upload_limit=lambda: 10_000, session_user=lambda t: "u1" if t == "live" else None
    )

    async def sent(message):
        if message["type"] == "http.response.start":
            answered.append(message["status"])

    async def nothing():
        return {"type": "http.request", "body": b"", "more_body": False}

    def call(path, length, key="k", token="live"):
        scope = {
            "type": "http",
            "method": "POST",
            "path": path,
            "client": ("10.0.0.5", 1),
            "headers": [
                (b"content-type", b"multipart/form-data; boundary=x"),
                (b"content-length", str(length).encode()),
                (b"mk-conn-key", key.encode()),
                (b"cookie", f"mk_session={token}".encode()),
            ],
        }
        asyncio.run(mw(scope, nothing, sent))
        return answered[-1]

    # Declared lengths on /connector reserve nothing: each is answered by the route.
    for key in ("a", "b", "c"):
        assert call("/connector/v1/accounts/x/files", 900, key) == 403
    # Elsewhere, a declared length is held; past everyone's ceiling, refused at once.
    mw.in_flight = {"user:u2": 900}
    assert call("/ui/api/receipts", 700) == 503  # everyone's ceiling (CR3-56)
    mw.in_flight = {"user:u1": 900}
    assert call("/ui/api/receipts", 200) == 429  # the user's own
    # CR3-56: an upload to /ui/api without a live session is refused on its headers.
    mw.in_flight = {}
    assert call("/ui/api/receipts", 500, token="forged") == 401
    assert mw.in_flight == {}
    mw.in_flight = {}
    assert call("/ui/api/receipts", 700) == 403


def test_an_upload_without_a_live_session_is_refused_before_its_body_is_read(server):
    """CR3-56 (S13.7.6): through the whole app, a 5 MB upload with a forged session cookie
    is answered 401 on its headers; next to none of its body is read."""
    import asyncio

    from moolakata.app import create_app

    app = create_app(server)
    size, chunk = 5 * 1024 * 1024, 64 * 1024
    taken = 0
    statuses = []

    async def receive():
        nonlocal taken
        taken += chunk
        return {"type": "http.request", "body": b"x" * chunk, "more_body": taken < size}

    async def send(message):
        if message["type"] == "http.response.start":
            statuses.append(message["status"])

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/ui/api/receipts",
        "raw_path": b"/ui/api/receipts",
        "query_string": b"",
        "scheme": "http",
        "server": ("mk.test", 80),
        "client": ("127.0.0.1", 50000),
        "http_version": "1.1",
        "headers": [
            (b"host", b"mk.test"),
            (b"origin", b"http://mk.test"),
            (b"content-type", b"multipart/form-data; boundary=x"),
            (b"content-length", str(size).encode()),
            (b"cookie", b"mk_session=forged-not-a-session"),
        ],
    }
    asyncio.run(app(scope, receive, send))
    assert statuses == [401]
    assert taken <= chunk, "the body was not read"
