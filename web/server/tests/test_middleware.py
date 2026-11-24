import pytest
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
        mw = ClientAddress(app, "proxy", tuple(ipaddress.ip_address(t) for t in trusted))
        scope = {
            "type": "http",
            "client": (peer, 1),
            "scheme": "http",
            "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
        }
        asyncio.run(mw(scope, None, None))
        return dict(seen)

    fwd = {"x-forwarded-for": "203.0.113.9, 10.0.0.2", "x-forwarded-proto": "https"}
    both = ["10.0.0.1", "10.0.0.2"]
    assert call("10.0.0.1", fwd, both) == {"client": "203.0.113.9", "scheme": "https"}
    # A proxy in the chain not named is the client: a range never stands in for it (S13.3).
    assert call("10.0.0.1", fwd, ["10.0.0.1"]) == {"client": "10.0.0.2", "scheme": "https"}
    assert call("10.0.0.3", fwd, ["10.0.0.1"]) == {"client": "10.0.0.3", "scheme": "http"}
    assert call("192.0.2.1", fwd, ["10.0.0.1"]) == {"client": "192.0.2.1", "scheme": "http"}


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
    # At most 100 MB arriving at once for one caller (S13.7.6), here a smaller cap.
    from conftest import make_user, sign_in

    from moolakata import middleware

    make_user(server, "jane")
    c = sign_in(server, "jane")
    monkeypatch.setattr(middleware, "IN_FLIGHT", 1000)
    r = c.post("/ui/api/receipts", files={"file": ("big.png", b"x" * 5000)})
    assert r.status_code == 413 and r.json()["code"] == "too-large", "alone past it: its size"
    r = c.post("/ui/api/receipts", files={"file": ("small.png", b"x" * 100)})
    assert r.status_code not in (413, 429), "the count is let go when a request ends"


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


def test_a_refusal_before_the_app_is_logged_by_its_id_and_titled_as_a_routes(bare_client, caplog):
    # S13.7.8: the middleware's refusals are in the log by their id, as a route's are;
    # S13.8.3: one status, one title, whoever answers it.
    import asyncio
    import json

    from moolakata import errors, middleware

    with caplog.at_level("INFO", logger="moolakata.errors"):
        r = bare_client.post("/ui/api/x", json={}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["title"] == errors.TITLES[403]
    line = f"problem {r.json()['errorId']} 403 origin-refused"
    assert any(rec.getMessage() == line for rec in caplog.records), caplog.text
    for status in (401, 404, 413, 429, 503):
        sent = []

        async def send(message, sent=sent):
            sent.append(message)

        asyncio.run(middleware._send_problem(status, "a-code", "Words.")(send))
        body = json.loads(sent[1]["body"])
        assert body["title"] == errors.TITLES[status], status
        assert sent[0]["headers"][0] == (b"content-type", b"application/problem+json")


def test_the_connectors_uploads_count_as_read_and_everyones_have_a_ceiling(monkeypatch):
    """S13.7.6: a call to /connector reserves nothing for what it says it carries, so a stranger's
    key header holds no budget (its route reads a body only once the paired connector's signature
    checks out); and all callers together have a ceiling."""
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
    assert call("/ui/api/receipts", 700) == 503  # everyone's ceiling
    mw.in_flight = {"user:u1": 900}
    assert call("/ui/api/receipts", 200) == 429  # the user's own
    # An upload to /ui/api without a live session is refused on its headers.
    mw.in_flight = {}
    assert call("/ui/api/receipts", 500, token="forged") == 401
    assert mw.in_flight == {}
    mw.in_flight = {}
    assert call("/ui/api/receipts", 700) == 403


@pytest.mark.parametrize("mb", [1, 19, 20, 100])
def test_an_upload_is_counted_in_flight_whatever_its_size_limit(monkeypatch, mb):
    """S13.7.6: an upload is told by what it carries and where it goes, never by its limit's
    size: with Settings' larger limit at 19 MB (a limit of 20 MB, a linked server's JSON) or
    1 MB, a user's upload and the connector's statement still count against the 100 MB."""
    import asyncio

    from moolakata import middleware

    monkeypatch.setattr(middleware, "IN_FLIGHT", 1000)
    held = []

    async def app(scope, receive, send):  # reads the whole body, then answers
        while (await receive()).get("more_body"):
            pass
        held.append(dict(mw.in_flight))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    limit = lambda: (mb + 1) * 1024 * 1024  # noqa: E731 - as app.upload_cap makes it
    mw = middleware.BodyLimit(app, limit, limit, session_user=lambda t: "u1")
    answered = []

    async def sent(message):
        if message["type"] == "http.response.start":
            answered.append(message["status"])

    def call(path, length, declare=True):
        body = [b"x" * (length // 2), b"x" * (length - length // 2)]

        async def receive():
            part = body.pop(0)
            return {"type": "http.request", "body": part, "more_body": bool(body)}

        headers = [(b"content-type", b"multipart/form-data; boundary=x")]
        if declare:
            headers.append((b"content-length", str(length).encode()))
        scope = {
            "type": "http",
            "method": "POST",
            "path": path,
            "client": ("10.0.0.5", 1),
            "headers": [*headers, (b"cookie", b"mk_session=live")],
        }
        asyncio.run(mw(scope, receive, sent))
        return answered[-1]

    assert call("/ui/api/receipts", 600) == 200 and held[-1] == {"user:u1": 600}
    mw.in_flight = {"user:u1": 900}
    assert call("/ui/api/receipts", 200) == 429, "the user's own 100 MB"
    mw.in_flight = {}
    assert call("/connector/v1/accounts/x/files", 600) == 200
    assert held[-1] == {"connector": 600}, "the connector's, counted as read"
    mw.in_flight = {"connector": 900}
    assert call("/connector/v1/accounts/x/files", 200) == 429
    # A linked server's JSON is no upload: never counted.
    mw.in_flight = {}
    assert mw.limit_for("/link/v1/exchange", "application/json") == (middleware.LINK_LIMIT, False)


def test_a_file_of_the_largest_size_fits_in_flight_and_one_past_it_is_refused_for_its_size():
    """S13.7.6, S16.8, S16.10: a statement or receipt may be up to 100 MB, and one of that size,
    with its form, fits in the 100 MB one user may have in flight; one past it is refused 413
    for its size, never 429 *wait*, which could never succeed: declared, or counted as it is
    read, as the connector's are."""
    import asyncio

    from moolakata import middleware, settings

    assert settings.DEFINITIONS["importMaxMb"].check(settings.FILE_MAX_MB) == 100
    assert settings.DEFINITIONS["receiptMaxMb"].check(settings.FILE_MAX_MB) == 100
    for key in ("importMaxMb", "receiptMaxMb"):
        with pytest.raises(settings.Invalid):
            settings.DEFINITIONS[key].check(settings.FILE_MAX_MB + 1)

    async def app(scope, receive, send):  # reads the whole body, then answers
        while (await receive()).get("more_body"):
            pass
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    cap = lambda: (settings.FILE_MAX_MB + 1) * 1024 * 1024  # noqa: E731 - as app.upload_cap
    mw = middleware.BodyLimit(app, cap, cap, session_user=lambda t: "u1")
    answered = []
    piece = b"x" * (1024 * 1024)

    async def sent(message):
        if message["type"] == "http.response.start":
            answered.append(message["status"])

    def call(path, size, declare=True):
        left = size

        async def receive():
            nonlocal left
            n = min(left, len(piece))
            left -= n
            return {"type": "http.request", "body": piece[:n], "more_body": left > 0}

        headers = [(b"content-type", b"multipart/form-data; boundary=x")]
        if declare:
            headers.append((b"content-length", str(size).encode()))
        scope = {
            "type": "http",
            "method": "POST",
            "path": path,
            "client": ("10.0.0.5", 1),
            "headers": [*headers, (b"cookie", b"mk_session=live")],
        }
        asyncio.run(mw(scope, receive, sent))
        return answered[-1]

    largest = settings.FILE_MAX_MB * 1024 * 1024 + 300  # the file and its form
    past = middleware.IN_FLIGHT + 1
    assert call("/ui/api/imports", largest) == 200
    assert call("/ui/api/imports", past) == 413
    assert call("/ui/api/imports", past, declare=False) == 413
    assert call("/connector/v1/accounts/x/files", largest) == 200
    assert call("/connector/v1/accounts/x/files", past) == 413
    assert mw.in_flight == {}


def test_an_upload_without_a_live_session_is_refused_before_its_body_is_read(server):
    """S13.7.6: through the whole app, a 5 MB upload with a forged session cookie is answered 401 on
    its headers; next to none of its body is read."""
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


def test_a_bodiless_post_without_a_length_needs_no_session():
    """A POST with neither a length nor a chunked body has no body (RFC 9112 §6.3), as curl sends
    the welcome's first step; a chunked one to /ui/api still needs a session."""
    import asyncio

    from moolakata import middleware

    answered = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    mw = middleware.BodyLimit(app, upload_limit=lambda: 10_000, session_user=lambda t: None)

    async def sent(message):
        if message["type"] == "http.response.start":
            answered.append(message["status"])

    async def nothing():
        return {"type": "http.request", "body": b"", "more_body": False}

    def call(headers):
        scope = {"type": "http", "method": "POST", "path": "/ui/api/welcome/phrase",
                 "client": ("127.0.0.1", 1), "headers": headers}  # fmt: skip
        asyncio.run(mw(scope, nothing, sent))
        return answered[-1]

    assert call([]) == 200
    assert call([(b"content-length", b"0")]) == 200
    assert call([(b"transfer-encoding", b"chunked")]) == 401


def _asgi(mw, path="/ui/api/receipts", headers=(), body=(b"",), client=("10.0.0.5", 1)):
    """One request through a middleware, its body in the parts given: the response starts
    sent back, and the body sent after them."""
    import asyncio

    parts = list(body)
    out: list[dict] = []

    async def receive():
        part = parts.pop(0) if parts else b""
        return {"type": "http.request", "body": part, "more_body": bool(parts)}

    async def send(message):
        out.append(message)

    scope = {"type": "http", "method": "POST", "path": path, "client": client,
             "headers": [(k.encode(), v.encode()) for k, v in headers]}  # fmt: skip
    asyncio.run(mw(scope, receive, send))
    starts = [m for m in out if m["type"] == "http.response.start"]
    content = b"".join(m.get("body", b"") for m in out if m["type"] == "http.response.body")
    return starts, content


def _reading_app(answer_first=False):
    """An app that reads the whole body and answers 200; or answers first, then reads."""

    async def app(scope, receive, send):
        if answer_first:
            await send({"type": "http.response.start", "status": 200, "headers": []})
        while (await receive()).get("more_body"):
            pass
        if not answer_first:
            await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"" if answer_first else b"read"})

    return app


UPLOAD = ("content-type", "multipart/form-data; boundary=x")


def _refusal(starts, content):
    import json

    [start] = starts
    body = json.loads(content)
    return start["status"], body["code"], body["detail"], dict(start["headers"])


def test_each_refusal_of_a_body_says_its_status_code_and_words(monkeypatch):
    """S13.7.6: too large for its limit, an upload with no session, one user's uploads past
    theirs, and everyone's past the server's, each at its status, code and words."""
    from moolakata import middleware

    monkeypatch.setattr(middleware, "IN_FLIGHT", 3 * 1024 * 1024)
    monkeypatch.setattr(middleware, "IN_FLIGHT_ALL", 4 * 1024 * 1024)
    mw = middleware.BodyLimit(
        _reading_app(), lambda: 2 * 1024 * 1024, session_user=lambda t: "u1" if t == "s" else None
    )
    signed_in = ("cookie", "mk_session=s")
    status, code, detail, _ = _refusal(
        *_asgi(mw, headers=[("content-type", "application/json"), ("content-length", "1048577")])
    )
    assert (status, code, detail) == (413, "too-large", "The request is larger than 1 MB.")
    status, code, detail, _ = _refusal(
        *_asgi(mw, headers=[UPLOAD, signed_in, ("content-length", str(2 * 1024 * 1024 + 1))])
    )
    assert (status, code, detail) == (413, "too-large", "The request is larger than 2 MB.")
    status, code, detail, _ = _refusal(*_asgi(mw, headers=[UPLOAD, ("content-length", "10")]))
    assert (status, code, detail) == (401, "not-signed-in", "Sign in to continue.")
    mw.in_flight = {"user:u1": 2 * 1024 * 1024}
    status, code, detail, headers = _refusal(
        *_asgi(mw, headers=[UPLOAD, signed_in, ("content-length", str(1024 * 1024 + 1))])
    )
    assert (status, code) == (429, "uploads-in-flight")
    assert detail == "More than 100 MB of uploads are arriving at once. Wait for them to finish."
    assert headers[b"retry-after"] == b"10"
    mw.in_flight = {"user:u2": 3 * 1024 * 1024}
    status, code, detail, headers = _refusal(
        *_asgi(mw, headers=[UPLOAD, signed_in, ("content-length", str(1024 * 1024 + 1))])
    )
    assert (status, code) == (503, "uploads-busy")
    assert detail == "The server is taking in as many uploads as it can. Try again in a moment."
    assert headers[b"retry-after"] == b"30"


def test_uploads_counted_as_they_arrive_are_refused_past_everyones_ceiling(monkeypatch):
    """S13.7.6: a body with no length is counted as it is read: past every caller's ceiling it
    is refused 503 before the app answers; once the app has answered, nothing more is sent;
    either way its count is let go."""
    from moolakata import middleware

    monkeypatch.setattr(middleware, "IN_FLIGHT", 1000)
    monkeypatch.setattr(middleware, "IN_FLIGHT_ALL", 1500)
    chunked = ("transfer-encoding", "chunked")
    for answer_first, expected in ((False, 503), (True, 200)):
        mw = middleware.BodyLimit(_reading_app(answer_first), lambda: 10_000, session_user=str)
        mw.in_flight = {"user:u2": 1000}
        starts, content = _asgi(
            mw, headers=[UPLOAD, chunked, ("cookie", "mk_session=u1")], body=[b"x" * 300] * 3
        )
        assert [s["status"] for s in starts] == [expected]
        if answer_first:
            assert content == b"", "the answer was started: the refusal isn't sent after it"
        assert mw.in_flight == {"user:u2": 1000}


def test_a_body_past_its_limit_or_its_callers_once_answered_sends_nothing_more(monkeypatch):
    from moolakata import middleware

    monkeypatch.setattr(middleware, "IN_FLIGHT", 1000)
    headers = [UPLOAD, ("transfer-encoding", "chunked"), ("cookie", "mk_session=u1")]
    mw = middleware.BodyLimit(_reading_app(answer_first=True), lambda: 600, session_user=str)
    starts, content = _asgi(mw, headers=headers, body=[b"x" * 400] * 2)
    assert [s["status"] for s in starts] == [200] and content == b""
    mw = middleware.BodyLimit(_reading_app(answer_first=True), lambda: 5000, session_user=str)
    mw.in_flight = {"user:u1": 900}
    starts, content = _asgi(mw, headers=headers, body=[b"x" * 400] * 2)
    assert [s["status"] for s in starts] == [200] and content == b""
    assert mw.in_flight == {"user:u1": 900}


def test_an_upload_to_a_link_counts_against_its_key_or_else_its_address():
    """S13.7.6: a sealed receipt to /link with no key header counts against the address it came
    from, or none named when there is none."""
    from moolakata import middleware

    held = []

    async def app(scope, receive, send):
        await receive()
        held.append(dict(mw.in_flight))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    mw = middleware.BodyLimit(app, lambda: 10_000)
    sealed = [("content-type", "application/octet-stream"), ("content-length", "5")]
    _asgi(mw, "/link/v1/receipts", sealed, [b"12345"])
    _asgi(mw, "/link/v1/receipts", sealed, [b"12345"], client=None)
    _asgi(mw, "/link/v1/receipts", [*sealed, ("mk-link-key", "k1")], [b"12345"])
    # Declared lengths are held for an address; a key's is counted as it is read.
    assert held == [{"address:10.0.0.5": 5}, {"address:-": 5}, {"key:k1": 5}]
    assert mw.in_flight == {}


def test_a_malformed_cookie_is_no_session():
    from moolakata import middleware

    assert middleware.BodyLimit._token({b"cookie": "mk_session=x; $Bad=1"}) is None
    assert middleware.BodyLimit._token({b"cookie": "mk_session=x"}) == "x"
    assert middleware.BodyLimit._token({}) is None


def test_the_forwarded_host_and_a_proxy_with_no_chain_are_taken_as_s13_3_says():
    """From a trusted proxy (S13.3): no X-Forwarded-For leaves the proxy the client, a proto
    other than http or https is left alone, and X-Forwarded-Host stands for Host."""
    import asyncio
    import ipaddress

    from moolakata.middleware import ClientAddress

    seen = {}

    async def app(scope, receive, send):
        seen.update(client=scope["client"][0], scheme=scope["scheme"], headers=scope["headers"])

    mw = ClientAddress(app, "proxy", (ipaddress.ip_address("10.0.0.1"),))
    headers = {"host": "proxy.lan", "x-forwarded-proto": "ws", "x-forwarded-host": "mk.example"}
    scope = {"type": "http", "client": ("10.0.0.1", 1), "scheme": "https",
             "headers": [(k.encode(), v.encode()) for k, v in headers.items()]}  # fmt: skip
    asyncio.run(mw(scope, None, None))
    assert seen["client"] == "10.0.0.1" and seen["scheme"] == "https"
    assert [v for k, v in seen["headers"] if k == b"host"] == [b"mk.example"]


def test_an_address_that_isnt_one_is_outside_every_range():
    """S16.14: a client named by no address (a test client's) reaches only what is open to
    any address."""
    from moolakata.middleware import AddressRanges

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    mw = AddressRanges(app, lambda: {"app": ["10.0.0.0/8"]})
    status, code, detail, _ = _refusal(*_asgi(mw, "/ui/api/x", client=("testclient", 1)))
    assert (status, code, detail) == (404, "not-found", "Not found.")
    starts, _ = _asgi(mw, "/healthz", client=("testclient", 1))
    assert starts[0]["status"] == 200


@pytest.mark.parametrize(
    ("state", "detail", "retry"),
    [
        ("locked", "MoolaKata is locked: an admin enters the recovery phrase to open it.", b"30"),
        ("starting", "MoolaKata is starting: ask again in a moment.", b"5"),
    ],
)
def test_a_locked_or_starting_server_answers_its_state_with_its_words(state, detail, retry):
    """S13.6: what isn't open while the server is locked or starting answers 503 with the state
    as its code, its words, when to ask again and never kept; what is open passes."""
    from moolakata.middleware import Locked

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    mw = Locked(app, lambda: state)
    for path in ("/ui/api/accounts", "/link/v1/hello", "/connector/v1/hello", "/mcp"):
        status, code, words, headers = _refusal(*_asgi(mw, path))
        assert (status, code, words) == (503, state, detail), path
        assert headers[b"retry-after"] == retry and headers[b"cache-control"] == b"no-store"
    for path in ("/ui/api/unlock", "/ui/app.js", "/healthz", "/demo"):
        assert _asgi(mw, path)[0][0]["status"] == 200, path


def test_a_201_answered_in_parts_names_its_location_once_whole():
    """S13.8.4: the body of a 201 sent in parts is gathered before its Location is worked out."""
    import asyncio
    import re
    from types import SimpleNamespace

    from moolakata.middleware import Created

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 201, "headers": []})
        await send({"type": "http.response.body", "body": b'{"id": ', "more_body": True})
        await send({"type": "http.response.body", "body": b'"Prsn_1"}'})

    out = []

    async def send(message):
        out.append(message)

    readers = [re.compile("/ui/api/persons/[^/]+")]
    served = SimpleNamespace(state=SimpleNamespace(api_readers=readers))
    scope = {"type": "http", "method": "POST", "path": "/ui/api/persons", "app": served}
    asyncio.run(Created(app)(scope, None, send))
    assert out[0]["headers"] == [(b"location", b"/ui/api/persons/Prsn_1")]
    assert out[1] == {"type": "http.response.body", "body": b'{"id": "Prsn_1"}'}
