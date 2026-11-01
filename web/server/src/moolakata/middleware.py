"""What every request passes through (requirements S13.7): the client's real address, the
response headers, the Origin check on changes, and the size of request bodies.

Plain ASGI middleware, so streaming responses (the live stream, receipt files) pass straight
through.
"""

import ipaddress
import json
import logging
import re
import time
from collections.abc import Callable

from .errors import new_error_id
from .links.sealed import max_receipt

log = logging.getLogger("moolakata.access")

APP_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
    "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; "
    "form-action 'self'; frame-ancestors 'none'"
)

COMMON_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"cross-origin-resource-policy", b"same-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
]
HSTS = (b"strict-transport-security", b"max-age=31536000")

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
JSON_LIMIT = 1024 * 1024
# A linked server's change (S11.4) may carry an item's transactions: the ceiling of an answer.
LINK_LIMIT = 20 * 1024 * 1024


def _send_problem(status: int, code: str, detail: str, headers=()):
    body = json.dumps(
        {
            "type": f"https://moolakata.invalid/problems/{code}",
            "title": {403: "Not allowed", 413: "Too large", 503: "Not available"}.get(
                status, "Error"
            ),
            "status": status,
            "detail": detail,
            "code": code,
            "errorId": new_error_id(),
            "errors": [],
        }
    ).encode()

    async def respond(send):
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/problem+json"),
                    (b"content-length", str(len(body)).encode()),
                    *headers,
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    return respond


class ClientAddress:
    """In proxy mode, believe X-Forwarded-For and -Proto only from the configured proxies; in
    tls mode, ignore them (S13.3)."""

    def __init__(self, app, mode: str, trusted: tuple):
        self.app = app
        self.mode = mode
        self.trusted = trusted

    def _is_trusted(self, host: str) -> bool:
        try:
            addr = ipaddress.ip_address(host)
        except ValueError:
            return False
        return any(addr in net for net in self.trusted)

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket") and self.mode == "proxy" and scope.get("client"):
            peer = scope["client"][0]
            if self._is_trusted(peer):
                headers = {k.lower(): v.decode("latin-1") for k, v in scope["headers"]}
                chain = [
                    h.strip() for h in headers.get(b"x-forwarded-for", "").split(",") if h.strip()
                ]
                client = peer
                for hop in reversed(chain):
                    client = hop
                    if not self._is_trusted(hop):
                        break
                proto = headers.get(b"x-forwarded-proto", "").split(",")[0].strip()
                scope = dict(scope)
                scope["client"] = (client, 0)
                if proto in ("http", "https"):
                    scope["scheme"] = proto
                forwarded_host = headers.get(b"x-forwarded-host", "").split(",")[0].strip()
                if forwarded_host:
                    scope["headers"] = [(k, v) for k, v in scope["headers"] if k.lower() != b"host"]
                    scope["headers"].append((b"host", forwarded_host.encode("latin-1")))
        await self.app(scope, receive, send)


class SecurityHeaders:
    """The headers of S13.7.7 on every response. A route that needs another CSP (the app's
    page with its nonce, the demo, a receipt file) sets its own, which is kept."""

    def __init__(self, app, tls: bool):
        self.app = app
        self.tls = tls

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def wrapped(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                names = {k.lower() for k, _ in headers}
                if b"content-security-policy" not in names:
                    headers.append((b"content-security-policy", APP_CSP.encode()))
                headers.extend(h for h in COMMON_HEADERS if h[0] not in names)
                if self.tls:
                    headers.append(HSTS)
                message = dict(message, headers=headers)
            await send(message)

        await self.app(scope, receive, wrapped)


class AddressRanges:
    """Only the address ranges Settings › Network allows reach each path (S16.14): the app
    (`/ui`, and `/mcp` with it), `/link` and `/connector`; `/healthz` and `/demo` answer any
    address. An address outside answers 404, as for what doesn't exist. The ranges are read
    for each request, so a change applies to the next one (R3.7)."""

    PATHS = (("/ui", "app"), ("/mcp", "app"), ("/link", "link"), ("/connector", "connector"))

    def __init__(self, app, ranges: Callable[[], dict[str, list[str]]]):
        self.app = app
        self.ranges = ranges

    @staticmethod
    def _allowed(addr: str, ranges: list[str]) -> bool:
        if not ranges:
            return True
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        return any(ip in ipaddress.ip_network(r) for r in ranges)

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket") and scope.get("client"):
            path = scope["path"]
            which = next((w for p, w in self.PATHS if path == p or path.startswith(p + "/")), None)
            if which is not None:
                ranges = self.ranges().get(which) or []
                if not self._allowed(scope["client"][0], ranges):
                    await _send_problem(404, "not-found", "Not found.")(send)
                    return
        await self.app(scope, receive, send)


class OriginCheck:
    """A request that changes something must come from the app's own origin (S13.7.4)."""

    def __init__(self, app, prefixes=("/ui/",)):
        self.app = app
        self.prefixes = prefixes

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] == "http"
            and scope["method"] not in SAFE_METHODS
            and scope["path"].startswith(self.prefixes)
        ):
            headers = {k.lower(): v.decode("latin-1") for k, v in scope["headers"]}
            origin = headers.get(b"origin")
            host = headers.get(b"host", "")
            expected = f"{scope.get('scheme', 'http')}://{host}"
            if not origin or origin != expected:
                await _send_problem(
                    403, "origin-refused", "This request did not come from MoolaKata's own page."
                )(send)
                return
        await self.app(scope, receive, send)


# Uploads arriving at once, per user (S13.7.6): 100 MB, and never less than one receipt of the
# largest size a linked server may deliver, sealed; and for the whole server, 256 MB.
IN_FLIGHT = max(100 * 1024 * 1024, max_receipt())
IN_FLIGHT_ALL = max(256 * 1024 * 1024, IN_FLIGHT)  # every caller together (CR3-56)
# A body past this to /ui/api is an upload's: its session is checked before it is read.
SIGNED_IN_PAST = 64 * 1024


class BodyLimit:
    """JSON bodies up to 1 MB; uploads (multipart) up to the size Settings allow, and at most
    100 MB of them arriving at once for one caller (S13.7.6): a signed-in user, whose session is
    checked on the headers before a byte of the body is read, a linked server's key or the
    connector, else an address; and at most 256 MB for every caller together.
    The connector's and a linked server's are counted as they are read, never by what a call
    says it carries: the gate reads a body only once its signature checks out (protocol §3.2,
    link-protocol.md §3.2).
    """

    def __init__(
        self,
        app,
        upload_limit: Callable[[], int],
        import_limit: Callable[[], int] | None = None,
        session_user: Callable[[str], str | None] | None = None,
    ):
        self.app = app
        self.upload_limit = upload_limit
        self.import_limit = import_limit or upload_limit
        self.session_user = session_user or (lambda token: None)
        self.in_flight: dict[str, int] = {}

    def limit_for(self, path: str, ctype: str) -> int:
        """The most a request's body may hold, by where it goes and what it carries."""
        to_link = path.startswith("/link/")
        if to_link and ctype.startswith("application/octet-stream"):
            # A receipt a linked server delivers, sealed (link-protocol.md §1.4, §4.3): up to
            # the largest receipt Settings allows, whatever this server's own setting.
            return max_receipt()
        if ctype.startswith("multipart/"):
            if path.startswith("/connector/"):
                return self.import_limit()  # statements, Settings › Imports' size (S16.8)
            return self.upload_limit()
        return LINK_LIMIT if to_link else JSON_LIMIT

    @staticmethod
    def _token(headers: dict) -> str | None:
        from http.cookies import SimpleCookie

        from .auth.sessions import COOKIE

        cookie = SimpleCookie()
        try:
            cookie.load(headers.get(b"cookie", ""))
        except Exception:  # a malformed cookie is no session
            return None
        return cookie[COOKIE].value if COOKIE in cookie else None

    def _caller(self, scope, headers: dict) -> str | None:
        """Whom an upload counts against: a signed-in user (their session checked on the
        headers, before a byte of the body is read: None when there is none, CR3-56), a linked
        server's key or the connector, else an address."""
        if scope["path"].startswith("/ui/api/"):
            token = self._token(headers)
            user = self.session_user(token) if token else None
            return f"user:{user}" if user else None
        if scope["path"].startswith("/connector/"):
            return "connector"
        if headers.get(b"mk-link-key"):
            return "key:" + headers[b"mk-link-key"]
        client = scope.get("client")
        return "address:" + (client[0] if client else "-")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in SAFE_METHODS:
            await self.app(scope, receive, send)
            return
        headers = {k.lower(): v.decode("latin-1") for k, v in scope["headers"]}
        ctype = headers.get(b"content-type", "")
        limit = self.limit_for(scope["path"], ctype)
        too_large = _send_problem(
            413, "too-large", f"The request is larger than {limit // (1024 * 1024)} MB."
        )
        length = headers.get(b"content-length")
        if length and length.isdigit() and int(length) > limit:
            await too_large(send)
            return
        upload = limit != JSON_LIMIT and limit != LINK_LIMIT
        big = scope["path"].startswith("/ui/api/") and (
            not length or not length.isdigit() or int(length) > SIGNED_IN_PAST
        )
        who = self._caller(scope, headers) if upload or big else ""
        if who is None:
            await _send_problem(401, "not-signed-in", "Sign in to continue.")(send)
            return
        # What it says it carries is held for it before the app runs, so a caller past the
        # cap is answered at once; a body without a length is counted as it arrives, and so are
        # the connector's and a linked server's, read only once their signature is checked
        # (links/gate.py), so the key a call names costs that key nothing until then.
        declared = int(length) if upload and length and length.isdigit() else 0
        if who == "connector" or who.startswith("key:"):
            declared = 0
        everyone = sum(self.in_flight.values())
        if upload and everyone + declared > IN_FLIGHT_ALL:
            await _server_busy(send)
            return
        if upload and self.in_flight.get(who, 0) + declared > IN_FLIGHT:
            await _send_problem(
                429,
                "uploads-in-flight",
                "More than 100 MB of uploads are arriving at once. Wait for them to finish.",
                [(b"retry-after", b"10")],
            )(send)
            return
        if upload:
            self.in_flight[who] = self.in_flight.get(who, 0) + declared
        seen = 0
        started = False

        async def counted():
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                n = len(message.get("body", b""))
                seen += n
                if seen > limit:
                    raise _TooLarge
                if upload and seen > declared:
                    self.in_flight[who] = self.in_flight.get(who, 0) + min(n, seen - declared)
                    if sum(self.in_flight.values()) > IN_FLIGHT_ALL:
                        raise _ServerBusy
                    if self.in_flight[who] > IN_FLIGHT:
                        raise _Busy
            return message

        async def tracking(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counted, tracking)
        except _TooLarge:
            if not started:
                await too_large(send)
        except _ServerBusy:
            if not started:
                await _server_busy(send)
        except _Busy:
            if not started:
                await _send_problem(
                    429,
                    "uploads-in-flight",
                    "More than 100 MB of uploads are arriving at once. Wait for them to finish.",
                    [(b"retry-after", b"10")],
                )(send)
        finally:
            if upload:
                left = self.in_flight.get(who, 0) - max(seen, declared)
                if left > 0:
                    self.in_flight[who] = left
                else:
                    self.in_flight.pop(who, None)


class _TooLarge(Exception):
    pass


class _ServerBusy(Exception):
    pass


async def _server_busy(send) -> None:
    """Every caller's uploads together past the server's ceiling (S13.7.6)."""
    await _send_problem(
        503,
        "uploads-busy",
        "The server is taking in as many uploads as it can. Try again in a moment.",
        [(b"retry-after", b"30")],
    )(send)


class _Busy(Exception):
    pass


class AccessLog:
    """One line per request: method, path, status, time. Never a query string, body or
    cookie, which could carry names or amounts (S13.7.9)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.monotonic()
        status = 0

        async def wrapped(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, wrapped)
        finally:
            user = scope.get("state", {}).get("user_id", "-")
            log.info(
                "%s %s %s %s %.0fms",
                scope["method"],
                scope["path"],
                status,
                user,
                (time.monotonic() - start) * 1000,
            )


class SessionCookie:
    """Writes the session cookie a route or dependency asked for (request.state.set_cookie):
    HttpOnly, Secure, SameSite=Strict, Path=/ui (S13.7.1). An empty value clears it."""

    def __init__(self, app, max_age: Callable[[], int]):
        self.app = app
        self.max_age = max_age

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def wrapped(message):
            if message["type"] == "http.response.start":
                token = scope.get("state", {}).get("set_cookie")
                if token is not None:
                    if token:
                        cookie = (
                            f"mk_session={token}; Path=/ui; Max-Age={self.max_age()}; "
                            "HttpOnly; Secure; SameSite=Strict"
                        )
                    else:
                        cookie = (
                            "mk_session=; Path=/ui; Max-Age=0; HttpOnly; Secure; SameSite=Strict"
                        )
                    message = dict(
                        message,
                        headers=[*message.get("headers", []), (b"set-cookie", cookie.encode())],
                    )
            await send(message)

        await self.app(scope, receive, wrapped)


class Locked:
    """While the server is locked or uninitialised (S13.6, S15.4), only what unlocking or the
    welcome needs answers: the app's page and files, the health check, the demo, the unlock
    route and the welcome's phrase and key. Everything else, the API, the link, connector and
    MCP listeners included, answers 503 `locked`."""

    OPEN = frozenset(
        {
            "/",
            "/healthz",
            "/demo",
            "/ui",
            "/ui/api/unlock",
            "/ui/api/welcome/phrase",
            "/ui/api/welcome/key",
        }
    )

    def __init__(self, app, locked: Callable[[], bool]):
        self.app = app
        self.locked = locked

    @classmethod
    def allowed(cls, path: str) -> bool:
        if path in cls.OPEN:
            return True
        return path.startswith("/ui/") and not path.startswith("/ui/api/")

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] in ("http", "websocket")
            and self.locked()
            and not self.allowed(scope["path"])
        ):
            await _send_problem(
                503,
                "locked",
                "MoolaKata is locked: an admin enters the recovery phrase to open it.",
                [(b"retry-after", b"30"), (b"cache-control", b"no-store")],
            )(send)
            return
        await self.app(scope, receive, send)


def location_of(path: str, body: bytes, readable=lambda where: True) -> str | None:
    """Where a 201's record is read (S13.8.4): the list's path and the new record's id; for an
    answer that is the record it was added to (a tax book with a new filing), that record;
    the list itself when the answer names no record, or the record has no path of its own
    that reads it (`readable`); and None, no `Location`, when nothing reads it."""
    try:
        made = json.loads(body).get("id") if body else None
    except ValueError, AttributeError:
        made = None
    parts = path.rstrip("/").split("/")
    if isinstance(made, str) and made:
        own = (
            "/".join(parts[: parts.index(made) + 1]) if made in parts else "/".join([*parts, made])
        )
        if readable(own):
            return own
    listed = "/".join(parts)
    return listed if readable(listed) else None


def _reads(scope, path: str) -> bool:
    """Whether a GET of the path is answered by one of the API's own routes (never the app's
    pages, which answer any path under /ui). Read from the app's OpenAPI document: FastAPI
    keeps included routers' routes out of the app's own route list."""
    app = scope["app"]
    readers = getattr(app.state, "api_readers", None)
    if readers is None:
        readers = [
            re.compile(
                "/".join("[^/]+" if x.startswith("{") else re.escape(x) for x in p.split("/"))
            )
            for p, ops in app.openapi()["paths"].items()
            if p.startswith("/ui/api/") and "get" in ops
        ]
        app.state.api_readers = readers
    return any(r.fullmatch(path) for r in readers)


class Created:
    """A 201 of the API names what it made in `Location` (S13.8.4): the route's own, or one
    worked out from its answer; none when nothing reads it, rather than a path that doesn't."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/ui/api/"):
            await self.app(scope, receive, send)
            return
        held: dict | None = None
        chunks: list[bytes] = []

        async def wrapped(message):
            nonlocal held
            if message["type"] == "http.response.start":
                named = any(k.lower() == b"location" for k, _ in message.get("headers", []))
                if message["status"] == 201 and not named:
                    held = message
                    return
            elif held is not None and message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))
                if message.get("more_body"):
                    return
                body = b"".join(chunks)
                where = location_of(scope["path"], body, lambda w: _reads(scope, w))
                found = [(b"location", where.encode())] if where else []
                await send({**held, "headers": [*held.get("headers", []), *found]})
                message = {"type": "http.response.body", "body": body}
            await send(message)

        await self.app(scope, receive, wrapped)
